import { createRoot } from "react-dom/client";
import App from "./App";
import "./styles.css";
import "./overhaul.css";
import "./assets/fonts/fonts.css";
import "./design.css";
import "./demo-lab.css";
import "./demo-investigation.css";
import "./demo-cases.css";

createRoot(document.getElementById("root") as HTMLElement).render(<App />);
