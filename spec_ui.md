# Specification: Legion OS — Futuristic UI Control Center

## Environment Audit (Standing Rule)
1. **Local System Check:** Checked the workspace for HTML/JS/CSS files. Found `committee-os-manual.html` (documentation) but no active dashboard application.
2. **Open-Source Check:** For building a custom dashboard UI, standard web technologies (HTML/CSS/JS) or a lightweight framework like React/Vite or Python-based frameworks like Streamlit/Gradio are typically used. Since we want a highly customized, futuristic sci-fi tactical aesthetic (matching the image exactly), a custom HTML/CSS/JS single-page application (SPA) or a React/Vite app is the most flexible and precise way to build it.
3. **Conclusion:** Proceeding with a custom HTML/CSS/JS single-page application (SPA) to implement the dashboard UI.

---

## Objective
Build a localized, unified control center for Legion OS based on the static visual layout in `Futuristic_UI_design_for_Legion_202607031016.jpeg`. The interface must be organized into a clean, multi-column dashboard with a sci-fi tactical aesthetic (dark mode, neon blue accents, clean panel borders).

---

## Interface Components

1. **Top Banner (Header):**
   - **Left:** Project identity branding ("LEGION" logo with a sci-fi icon).
   - **Center:** **System Monitor** tracking CPU and RAM telemetry (circular gauges) and Latency (line chart).
   - **Right:** **Token Monitor** tracking context windows against a 500,000 token ceiling (progress bar).

2. **Leftmost Column (Files):**
   - A native file-tree directory viewer showing a nested structure of home folders, data loads, data formats, and active files. Clicking a file loads its preview in the Document Preview Frame.

3. **Second Column (Document Preview Frame):**
   - A rich content viewer displaying:
     - Raw text blocks from a selected `.txt` file.
     - A tabular visualization of a `.xlsx` sheet.
     - A preview block of a `.docx` file.

4. **Center Column (AI Chat Core):**
   - The primary execution terminal featuring a standard user-to-system conversational message thread.
   - A clean text ingestion input field with a "Send" trigger.

5. **Right Column (Utility Panel & Community):**
   - **Top:** A real-time Markdown notepad scratchpad tool with formatting controls (Bold, Italic, Link, Code, Bullet, List).
   - **Bottom:** An embedded community communications sidebar widget (Discord-like channel view).

---

## Committee Task
1. Analyze the layout. Provide a brief, objective critique of the multi-column design and usability.
2. Propose a concrete action plan for implementing this UI as a single-page application (SPA) using HTML, CSS, and JavaScript, integrating with the Legion OS backend (SQLite and the `LegionStateMachine`).
3. Detail how the UI will fetch and display real-time telemetry (CPU, RAM, token counts) and file-tree data from the local system.
