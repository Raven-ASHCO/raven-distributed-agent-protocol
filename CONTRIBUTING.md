# Contributing to RDAP

This repository is the published `agent_team/` snapshot of RAVEN (version 1.1.0).
Protocol-codec edits belong in the RAVEN monorepo and are synced here; do not
patch `protocol/reference/raven_protocol/` in this tree.

## Code of Conduct

- Be respectful and constructive in all communications
- Focus on the code, not the person
- Welcome newcomers and help them get started

## How to Contribute

### Reporting Bugs

1. Search existing issues to avoid duplicates
2. Include the exact `./rdap` / `rdap.cmd` commands, OS, and Python version
3. Include `./rdap doctor` output when install or first-run is involved
4. Include expected vs actual behavior

### Suggesting Features

1. Open an issue with the `[Feature Request]` prefix
2. Describe the use case and expected behavior
3. Explain why this would benefit RDAP operators

### Security Issues

**Do NOT open public issues for security vulnerabilities.**
See [SECURITY.md](SECURITY.md) for responsible disclosure guidelines.

### Code Contributions

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/your-feature`)
3. Make your changes
4. Write/update tests if applicable (`team_agents/selftest.py`)
5. Ensure `./rdap try` (or `python -m team_agents.selftest`) exits 0
6. Submit a Pull Request with a clear description

## Development setup

Debian / Ubuntu need `python3-venv` (`sudo apt-get install python3 python3-venv python3-pip git`).

```bash
git clone https://github.com/Raven-ASHCO/raven-distributed-agent-protocol.git
cd raven-distributed-agent-protocol
./rdap try
```

On Windows use `rdap.cmd try`. That creates `.venv`, installs
`requirements.lock.txt` with hash verification, and runs the same suite as CI.

Useful commands:

```bash
./rdap doctor              # Python, Git, deps, signed-by-default, revocations_file
./rdap selftest            # full A2A suite
./rdap selftest --unit     # offline unit checks only
./rdap --help
```

Newcomer first-ask path: install → `try`/`doctor` → `init` → `start` → `invite`
→ `trust` → `ping` → `ask`. See the README checklist.

Protocol notes (honesty, not “already fixed”). Operator bridge:
[`docs/newcomer-task-lifecycle.md`](docs/newcomer-task-lifecycle.md). Freeze
baseline (do not rewrite): [`docs/rdap-task-lifecycle.md`](docs/rdap-task-lifecycle.md).

- Address deny-list / unset `TEAM_REVOCATIONS` footgun: [`docs/rdap-revocation.md`](docs/rdap-revocation.md)
- Cancel store force-save vs executor/brain complete (open O5 gap, Role #14):
  [`docs/rdap-task-lifecycle.md`](docs/rdap-task-lifecycle.md) §9.1

OPEN MODE (`--open` / `TEAM_REQUIRE_SIGNED=0`) must stay off unless a test is
explicitly covering that escape hatch. Do not add a default-on path.

Runtime/CI installs must use `requirements.lock.txt`, not `requirements.txt`.

## License

By contributing, you agree that your contributions will be licensed under the AGPL-3.0 License.
