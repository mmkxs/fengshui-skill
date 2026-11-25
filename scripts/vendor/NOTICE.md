# Vendored dependency

## lunar-python 1.4.8

- Upstream: https://github.com/6tail/lunar-python  ·  PyPI: `lunar-python`
- License: **MIT** — full text in `LICENSE-lunar-python`
- Why vendored: pure Python, zero dependencies, ~460KB. Vendoring keeps this skill
  **offline & self-contained** and **pins the API surface** the scripts rely on
  (`getEightChar`, `getDayYi/getDayJi`, `getZhiXing`, `getDayTianShen*`, `getXiu*`,
  `getPengZu*`, `getDayChongDesc`, `getDaySha`, `getDayJiShen`, `getDayXiongSha`,
  `getDayPosition*`, `getDayNineStar`, `getTimes`).
- Not modified. Do not edit files under `lunar_python/` — re-vendor instead.

To re-vendor:
    pip download lunar-python==1.4.8 -d /tmp/lp --no-deps
    tar xzf /tmp/lp/lunar_python-1.4.8.tar.gz -C /tmp/lp --strip-components=1
    cp -r /tmp/lp/lunar_python  scripts/vendor/
    cp    /tmp/lp/LICENSE       scripts/vendor/LICENSE-lunar-python
