QuickAI

QuickAI is a small Linux desktop tool for running common text actions with an
OpenAI-compatible language model. The model may run locally through Ollama,
vLLM, LM Studio, LocalAI, or any other compatible service.


What it does
------------

QuickAI can:

  - read selected text from Linux desktop applications;
  - fix grammar, rewrite, shorten, expand, explain, and translate text;
  - create email replies, commit messages, and Markdown agent prompts;
  - replace the selected text with the result;
  - provide a browser interface for longer input and custom actions;
  - work from the command line, X11, and Wayland.


Requirements
------------

You need:

  - Linux;
  - Python 3.10 or newer;
  - python3-venv;
  - systemd for background service installation;
  - an OpenAI-compatible LLM API.

The browser interface does not require a frontend build step.


Installation
------------

1. Clone the repository.

       git clone https://github.com/rayanweragala/QuickAi.git quickai
       cd quickai

2. Install and start the QuickAI user service.

       ./install.sh

3. Open QuickAI.

       http://127.0.0.1:7431

4. Open Settings and enter the LLM API URL, model, and optional API key.

5. Install desktop integration if global hotkeys are required.

       ./scripts/setup-desktop.sh

6. Check the desktop integration.

       qa doctor


Basic use
---------

Select text in an application and use one of these shortcuts:

  - Ctrl+Alt+Space opens the action menu;
  - Ctrl+Alt+G fixes grammar;
  - Ctrl+Alt+P polishes text;
  - Ctrl+Alt+R writes an email reply;
  - Ctrl+Alt+M creates a Markdown agent prompt;
  - Ctrl+Alt+A asks a question;
  - Ctrl+Alt+Z restores the previous text to the clipboard.

The same actions are available from the command line:

       qa run grammar
       qa run polish
       qa menu
       qa ask "Explain this command"
       qa actions


Local test
----------

The included mock LLM allows testing without a model or API key.

1. Install Python dependencies.

       python3 -m venv .venv
       ./.venv/bin/pip install -r requirements.txt

2. Start the mock LLM in one terminal.

       ./.venv/bin/python scripts/mock_llm.py --stream

3. Start QuickAI in another terminal.

       QUICKAI_BASE_URL=http://127.0.0.1:8099 ./run.sh

4. Open http://127.0.0.1:7431 and run an action.


Tests
-----

Run the test suite from the repository root:

       ./.venv/bin/python -m unittest discover -s tests -v


Configuration
-------------

Service settings are stored in:

       ~/.config/quickai/config.json

Desktop client settings are stored in:

       ~/.config/quickai/client.json

Local environment values may be placed in .env. This file is ignored by Git.


Removal
-------

Remove the user service without deleting saved settings:

       ./uninstall.sh

Remove desktop hotkeys:

       ./scripts/hotkeys.sh remove
