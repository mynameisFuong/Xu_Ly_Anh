def pytest_addoption(parser):
    parser.addoption("--run-browser", action="store_true", default=False,
                     help="Run camera UI tests in installed Chrome with a synthetic camera")
