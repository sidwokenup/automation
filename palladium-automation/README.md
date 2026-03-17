# Palladium Automation Bot

This project is a Python-based automation tool using Playwright.

## Setup Instructions

1.  **Create Virtual Environment:**
    ```bash
    python -m venv venv
    ```

2.  **Activate Virtual Environment:**
    *   Windows: `venv\Scripts\activate`
    *   Mac/Linux: `source venv/bin/activate`

3.  **Install Dependencies:**
    ```bash
    pip install -r requirements.txt
    playwright install
    ```

4.  **Configuration:**
    *   Update `config/config.json` with your actual credentials.
    *   **Note:** Do not commit `config.json` with real credentials to version control.

## Run Project

To run the automation:

```bash
python main.py
```

## Features

*   Automated login to `https://next.palladium.expert`
*   Configurable via `config/config.json`
*   Logging to console and `logs/app.log`
