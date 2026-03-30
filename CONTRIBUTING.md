# Contributing to AgentLedger

Thanks for your interest in contributing. AgentLedger is open-source under Apache 2.0 and we welcome contributions of all kinds.

## Ways to Contribute

### Update Model Pricing
Model costs change constantly. If you spot outdated pricing in `pricing/models.json`, submit a PR with the current rates. Include your source (provider pricing page URL) in the PR description.

### Add Framework Integrations
We need callbacks for more agent frameworks:
- AutoGen
- Semantic Kernel
- Haystack
- Custom frameworks

Look at `agentledger-sdk/agentledger/integrations/langgraph.py` for the pattern.

### Improve Waste Detection
New waste patterns are always welcome. See `agentledger-server/app/workers/waste_detector.py`. Ideas:
- Idle heartbeat detection
- Duplicate work across agents
- Unnecessary context window stuffing

### Build the Dashboard
The React web dashboard (`agentledger-dashboard/`) needs to be built. If you're a frontend developer, this is the highest-impact contribution right now.

## Development Setup

```bash
# Clone
git clone https://github.com/Gameotivity/AgentLedger.git
cd AgentLedger

# Create virtual environment
python -m venv .venv
source .venv/bin/activate

# Install SDK in editable mode
pip install -e agentledger-sdk

# Install server deps
pip install fastapi uvicorn sqlalchemy aiosqlite pydantic pydantic-settings greenlet

# Install CLI
pip install -e agentledger-cli

# Run the server (SQLite by default for local dev)
cd agentledger-server
PYTHONPATH=. uvicorn app.main:app --port 8100 --reload

# Run the quickstart
python examples/basic/quickstart.py

# Check it worked
agentledger --project my-saas status
```

## Pull Request Process

1. Fork the repo and create a branch from `main`
2. If you've added code, add or update tests
3. Ensure your code passes `ruff check`
4. Update `pricing/models.json` if you've added model support
5. Write a clear PR description explaining what and why
6. Submit the PR

## Code Style

- Python 3.10+ with type hints
- Formatted with `ruff`
- No unnecessary abstractions — simple beats clever
- Callbacks must never break the user's LLM calls (wrap in try/except)

## Reporting Issues

Open an issue on GitHub with:
- What you expected to happen
- What actually happened
- Steps to reproduce
- Your environment (Python version, OS, framework versions)

## License

By contributing, you agree that your contributions will be licensed under the Apache 2.0 License.
