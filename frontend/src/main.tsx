import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";

import App from "./App";
import { PipelineProvider } from "./context/PipelineContext";
import "./index.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <PipelineProvider>
        <App />
      </PipelineProvider>
    </BrowserRouter>
  </React.StrictMode>,
);
