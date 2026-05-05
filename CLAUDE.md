# Project: Binary Shepard
## AI Agent Instructions

This project incorporates the **Everything Claude Code (ECC)** framework to ensure high-quality, secure, and performant code.

### 📜 Standards & Rules
All agents (Claude, Gemini, Antigravity, etc.) **must** adhere to the rules defined in the `.agent/rules/` directory:
- **Core Standards**: See `common-*.md` for general workflows and styles.
- **Language Specific**: 
  - Python: See `python-*.md`
  - Web/Frontend: See `web-*.md`
  - JavaScript/TypeScript: See `*-coding-style.md`

### 🛠️ Working with Antigravity
I (the agent) am using the Antigravity IDE. I have access to browser, shell, and file manipulation tools.
- **Rules Detection**: I have been configured to automatically scan the `.agent/` folder on startup.
- **Workflow**: 
  - `/plan`: Use the internal planning mode for complex changes.
  - `/verify`: Always run the verification suite before marking a task as done.

### 🚀 Custom Skills
ECC provides the following "Implicit personas" that I can adopt:
- **Architect**: For high-level system design.
- **Researcher**: For finding the best libraries or fixing obscure bugs.
- **Debugger**: For deep technical troubleshooting.
- **Refactorer**: For cleaning up technical debt.

---
*Created by Everything Claude Code (ECC) Installer v1.10.0*
