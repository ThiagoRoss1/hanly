import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./app/App.tsx";
import "./styles/index.css";

const root = document.getElementById("root");
if (!root) throw new Error("The Hanly application root element is missing.");

createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
