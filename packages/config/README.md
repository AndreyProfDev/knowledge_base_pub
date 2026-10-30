# knowledge-base-config

Structured settings for every package in this workspace.

A settings class is a **frozen** pydantic model that declares where its YAML
lives. The loader merges `base/*.yaml` then `<env>/*.yaml` from that directory,
resolves `${secret:...}` references against the environment, and validates the
result:

```python
from pathlib import Path
from typing import ClassVar

from knowledge_base_config import BaseSettings, Environment, load_settings


class MyToolSettings(BaseSettings):
    yaml_directory: ClassVar[Path] = Path(__file__).parent

    api_url: str
    token: str


def get_settings(env: Environment) -> MyToolSettings:
    return load_settings(MyToolSettings, env=env)
```

```yaml
# configs/base/my_tool.yaml
api_url: https://api.example.com
token: ${secret:my_tool_token,""}
```

`${secret:my_tool_token}` reads the **upper-cased** name from the environment —
`MY_TOOL_TOKEN`. In the `local` environment only, a `.env` file at the workspace
root is loaded first (with `override=False`, so an exported shell variable
always wins). `.env` is a convenience that pre-seeds `os.environ`, not a
separate configuration tier.

Rules of the road:

- Application code never calls `os.environ` directly. It reads a settings field.
- Tests select `Environment.TESTING` and a `configs/testing/` overlay instead of
  monkeypatching environment variables.
