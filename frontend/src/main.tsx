import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { FluentProvider, webLightTheme } from "@fluentui/react-components";

import App from "./App";
import "./index.css";

const el = document.getElementById("root");
if (!el) throw new Error("missing #root");

createRoot(el).render(
  <StrictMode>
    <FluentProvider theme={webLightTheme} style={{ minHeight: "100vh" }}>
      <App />
    </FluentProvider>
  </StrictMode>,
);
