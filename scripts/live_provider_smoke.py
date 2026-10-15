"""Run explicitly inside the VPS application container; uses its private environment."""

from vasa.provider_smoke import main

if __name__ == "__main__":
    raise SystemExit(main())
