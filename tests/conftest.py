"""Pytest configuration for AI Friend tests."""


def pytest_addoption(parser):
    parser.addoption(
        "--real-api",
        action="store_true",
        default=False,
        help="Run integration tests that require real DeepSeek API access",
    )
