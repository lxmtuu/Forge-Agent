"""Server-side model registry + capability routing cho nhiều provider.

``image_generation`` là capability contract; Phase 1 chưa có image adapter.
Client chọn model ID/capability, không gửi endpoint hay API key.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass

from . import config, llm

CAPABILITIES = frozenset({"code", "reasoning", "vision", "design", "image_generation", "tools"})


class ModelCapabilityError(ValueError):
    pass


@dataclass(frozen=True)
class ModelSpec:
    id: str
    provider: str
    model: str
    label: str
    capabilities: frozenset[str]
    source: str = "registry"
    adapter: str = "chat"

    def public(self) -> dict:
        return {"id": self.id, "provider": self.provider, "model": self.model,
                "label": self.label, "capabilities": sorted(self.capabilities),
                "source": self.source, "adapter": self.adapter}


def infer_capabilities(model_id: str) -> frozenset[str]:
    """Metadata routing bảo thủ; admin có thể override bằng config.models."""
    low = model_id.lower()
    caps = {"code", "reasoning", "tools"}
    # Không suy ra vision chỉ vì tên Claude/GPT/Kimi; live catalog bổ sung theo
    # input_modalities. Gemini direct và ID vision/VL có metadata multimodal rõ.
    if any(mark in low for mark in ("gemini", "vision", "/vl-", "-vl-", "-vl:")):
        caps.update({"vision", "design"})
    return frozenset(caps)


class ModelRegistry:
    def __init__(self) -> None:
        self._overrides: dict[str, ModelSpec] = {}
        self.reload()

    def reload(self) -> None:
        specs: dict[str, ModelSpec] = {}
        for model in config.DEFAULT_MODELS:
            spec = self.make_spec(f"openrouter:{model}")
            specs[spec.id] = spec
        # Gemini direct khác hoàn toàn google/... qua OpenRouter.
        for model in ("gemini-3.8-flash",):
            spec = self.make_spec(f"google:{model}")
            specs[spec.id] = spec
        cfg = config.load_config()
        configured = cfg.get("models") or []
        if isinstance(configured, list):
            for item in configured:
                if not isinstance(item, dict) or not item.get("id"):
                    continue
                spec = self.make_spec(str(item["id"]), capabilities=item.get("capabilities"),
                                      label=str(item.get("label") or ""))
                specs[spec.id] = spec
        self._overrides = specs

    @staticmethod
    def canonical(model: str | None, provider: str | None = None) -> str:
        raw = (model or "").strip()
        if not raw:
            raw = config.get_model()
        prefix, sep, bare = raw.partition(":")
        if sep and prefix.lower() in llm.PROVIDER_PREFIXES and not bare.strip():
            raise ValueError(f"Model ID thiếu tên sau prefix provider '{prefix}:'")
        # Không đoán google/... là Gemini direct: trên OpenRouter đó là vendor prefix.
        return llm.qualify_model(raw, provider)

    @classmethod
    def make_spec(cls, model: str, capabilities=None, label: str = "") -> ModelSpec:
        canonical = cls.canonical(model)
        provider, bare = llm.split_model_id(canonical)
        if provider not in llm.PROVIDER_PREFIXES or not bare:
            raise ValueError("Model ID không hợp lệ")
        caps = frozenset(str(c).strip() for c in capabilities) if capabilities is not None \
            else infer_capabilities(canonical)
        unknown = caps - CAPABILITIES
        if unknown:
            raise ValueError(f"Capability không hợp lệ: {sorted(unknown)}")
        if "image_generation" in caps:
            # Contract được khai báo nhưng không giả vờ có chat adapter tạo ảnh.
            raise ModelCapabilityError("Image-generation adapter chưa được bật trong Phase 1")
        return ModelSpec(id=canonical, provider=provider, model=bare,
                         label=label or bare, capabilities=caps)

    def get(self, model: str) -> ModelSpec:
        canonical = self.canonical(model)
        return self._overrides.get(canonical) or self.make_spec(canonical)

    def list(self, provider: str | None = None, capability: str | None = None) -> list[ModelSpec]:
        if capability is not None and capability not in CAPABILITIES:
            raise ValueError("Capability không hợp lệ")
        specs = sorted(self._overrides.values(), key=lambda s: (s.provider, s.id))
        return [s for s in specs if (provider is None or s.provider == provider)
                and (capability is None or capability in s.capabilities)]

    def route(self, capability: str = "code", requested: str | None = None) -> ModelSpec:
        if capability not in CAPABILITIES:
            raise ModelCapabilityError("Capability không hợp lệ")
        if capability == "image_generation":
            raise ModelCapabilityError("Image generation mới có contract; adapter sẽ nằm ở phase sau")
        if requested:
            spec = self.get(requested)
            if capability not in spec.capabilities:
                raise ModelCapabilityError(f"Model {spec.id} không khai báo capability {capability}")
            return spec
        for spec in self.list(capability=capability):
            return spec
        raise ModelCapabilityError(f"Không có model cho capability {capability}")

    def default_model(self) -> str:
        configured = self.canonical(config.get_model())
        # Legacy default của Google không được biến thành OpenRouter model thiếu vendor.
        if configured.startswith(("google:", "custom:")):
            return configured
        return self.route("code", configured).id


class ModelRouter:
    """Facade stateless: mỗi call lấy provider từ model ID của chính request."""

    def __init__(self, registry: ModelRegistry) -> None:
        self.registry = registry

    def canonical(self, model: str | None, parent: str | None = None) -> str:
        raw = model or parent or self.registry.default_model()
        provider = llm.split_model_id(parent)[0] if parent else None
        return self.registry.canonical(raw, provider)

    def default_model(self) -> str:
        return self.registry.default_model()

    def resolve(self, model: str | None) -> str:
        return llm.resolve_model(self.canonical(model))

    def resolve_sub_model(self, model: str | None, parent: str | None = None) -> str | None:
        raw = (model or "inherit").strip()
        low = raw.lower()
        if low in ("", "inherit", "same", "parent"):
            return None
        parent_provider = llm.split_model_id(parent)[0] if parent else None
        cfg = config.load_config()
        roles = cfg.get("model_roles") or {}
        if low in ("cheap", "free", "fast", "low"):
            role = str(roles.get("cheap") or "").strip()
            if role:
                return self.canonical(role)  # role cũ theo active config; nên dùng prefix mới
            return self.canonical("openrouter/free" if parent_provider == "openrouter" else parent,
                                  parent_provider)
        if low in ("strong", "best", "powerful", "high"):
            role = str(roles.get("strong") or "").strip()
            return self.canonical(role or parent or self.default_model(), parent_provider)
        return self.canonical(raw, parent_provider)

    def pick_fallback(self, model: str | None, error: Exception) -> str | None:
        canonical = self.canonical(model)
        fallback = llm.pick_fallback(canonical, error)
        return self.canonical(fallback, llm.split_model_id(canonical)[0]) if fallback else None

    def stream_chat(self, messages: list[dict], tools: list[dict] | None = None,
                    model: str | None = None, temperature: float = 0.3) -> AsyncIterator[dict]:
        return llm.stream_chat(messages, tools=tools, model=self.canonical(model),
                               temperature=temperature)


registry = ModelRegistry()
router = ModelRouter(registry)
