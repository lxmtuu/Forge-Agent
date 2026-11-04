import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import './styles.css'

// theme đã lưu áp NGAY khi boot (tránh nhấp nháy dark→light)
const savedTheme = localStorage.getItem('forge-theme')
if (savedTheme && savedTheme !== 'dark') document.documentElement.dataset.theme = savedTheme

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
