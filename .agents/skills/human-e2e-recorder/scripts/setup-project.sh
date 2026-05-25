#!/usr/bin/env bash
set -euo pipefail

MODE="setup"
if [[ "${1:-}" == "--inspect" ]]; then
  MODE="inspect"
fi

ROOT="$(pwd)"

detect_pm() {
  if [[ -f pnpm-lock.yaml ]]; then
    printf 'pnpm'
  elif [[ -f package-lock.json ]]; then
    printf 'npm'
  elif [[ -f yarn.lock ]]; then
    printf 'yarn'
  elif [[ -f bun.lockb || -f bun.lock ]]; then
    printf 'bun'
  else
    printf 'npm'
  fi
}

remote_cmd() {
  if command -v sfw > /dev/null 2>&1; then
    sfw "$@"
  else
    "$@"
  fi
}

pm_add_dev() {
  local pm="$1"
  shift
  local cmd=()
  case "$pm" in
    pnpm) cmd=("$pm" add -D "$@") ;;
    npm) cmd=("$pm" i -D "$@") ;;
    yarn) cmd=("$pm" add -D "$@") ;;
    bun) cmd=("$pm" add -d "$@") ;;
    *)
      printf 'Unsupported package manager: %s\n' "$pm" >&2
      return 2
      ;;
  esac
  remote_cmd "${cmd[@]}"
}

pm_playwright() {
  local pm="$1"
  shift
  local cmd=()
  case "$pm" in
    pnpm | yarn) cmd=("$pm" exec playwright "$@") ;;
    npm) cmd=("$pm" exec -- playwright "$@") ;;
    bun) cmd=("$pm"x playwright "$@") ;;
    *)
      printf 'Unsupported package manager: %s\n' "$pm" >&2
      return 2
      ;;
  esac
  remote_cmd "${cmd[@]}"
}

find_playwright_config() {
  local candidate
  for candidate in playwright.config.ts playwright.config.mts playwright.config.js playwright.config.mjs; do
    if [[ -f "$candidate" ]]; then
      printf '%s' "$candidate"
      return 0
    fi
  done
  return 1
}

detect_e2e_dirs() {
  find . -maxdepth 3 -type f \( -name "*.spec.ts" -o -name "*.e2e.ts" -o -name "*.test.ts" \) |
    sed 's#^\./##' |
    awk -F/ 'NF > 1 {print $1 "/" $2} NF == 1 {print "."}' |
    sort -u
}

has_dep() {
  local name="$1"
  [[ -f package.json ]] && node -e "const p=require('./package.json'); const d={...p.dependencies,...p.devDependencies}; process.exit(d[process.argv[1]]?0:1)" "$name" > /dev/null 2>&1
}

print_inspection() {
  local pm="$1"
  local config="${2:-}"
  printf 'HUMAN_E2E_INSPECT root=%s\n' "$ROOT"
  printf 'HUMAN_E2E_INSPECT package_manager=%s\n' "$pm"
  if [[ -n "$config" ]]; then
    printf 'HUMAN_E2E_INSPECT playwright_config=%s\n' "$config"
  else
    printf 'HUMAN_E2E_INSPECT playwright_config=missing\n'
  fi
  if has_dep electron || rg -q "_electron|electron" package.json . 2> /dev/null; then
    printf 'HUMAN_E2E_INSPECT app_type=electron-or-electron-capable\n'
  else
    printf 'HUMAN_E2E_INSPECT app_type=web-or-unknown\n'
  fi
  printf 'HUMAN_E2E_INSPECT e2e_dirs=\n'
  detect_e2e_dirs || true
  if [[ -f package.json ]]; then
    printf 'HUMAN_E2E_INSPECT package_scripts=\n'
    node -e "const p=require('./package.json'); for (const [k,v] of Object.entries(p.scripts||{})) console.log(k+': '+v)"
  fi
}

create_human_helper() {
  local dir="tests/e2e/support"
  local file="${dir}/human.ts"
  mkdir -p "$dir"
  if [[ -f "$file" ]]; then
    local backup
    backup="${file}.bak.$(date -u +%Y%m%dT%H%M%SZ)"
    cp "$file" "$backup"
    printf 'HUMAN_E2E_BACKUP %s\n' "$backup"
  fi
  cat > "$file" << 'TS'
import { expect, type Locator, type Page } from '@playwright/test';

type PauseRange = [number, number];

export function speedProfile() {
  const profile = process.env.HUMAN_E2E_SPEED ?? 'demo';
  switch (profile) {
    case 'fast':
      return { pause: [50, 100] as PauseRange, typing: [25, 80] as PauseRange };
    case 'normal':
      return { pause: [100, 250] as PauseRange, typing: [40, 120] as PauseRange };
    case 'slow':
      return { pause: [500, 900] as PauseRange, typing: [120, 260] as PauseRange };
    case 'demo':
    default:
      return { pause: [250, 500] as PauseRange, typing: [80, 180] as PauseRange };
  }
}

export async function humanPause(minMs: number, maxMs: number) {
  const delay = Math.floor(minMs + Math.random() * (maxMs - minMs + 1));
  await new Promise((resolve) => setTimeout(resolve, delay));
}

export async function humanType(locator: Locator, text: string, options: { minDelayMs?: number; maxDelayMs?: number } = {}) {
  const profile = speedProfile();
  const minDelayMs = options.minDelayMs ?? profile.typing[0];
  const maxDelayMs = options.maxDelayMs ?? profile.typing[1];
  await expect(locator).toBeVisible();
  for (const char of text) {
    await locator.pressSequentially(char, { delay: minDelayMs });
    await humanPause(minDelayMs, maxDelayMs);
  }
}

export async function humanClick(locator: Locator, options: { pauseAfterMs?: PauseRange } = {}) {
  const profile = speedProfile();
  await expect(locator).toBeVisible();
  await locator.click();
  const [minMs, maxMs] = options.pauseAfterMs ?? profile.pause;
  await humanPause(minMs, maxMs);
}

export async function humanScroll(page: Page, options: { deltaY?: number; steps?: number } = {}) {
  const steps = options.steps ?? 4;
  const deltaY = options.deltaY ?? 240;
  for (let index = 0; index < steps; index += 1) {
    await page.mouse.wheel(0, deltaY);
    await humanPause(120, 260);
  }
}

export async function humanMouseMove(page: Page, target: Locator, options: { steps?: number } = {}) {
  const box = await target.boundingBox();
  if (!box) {
    throw new Error('Cannot move mouse to target without a bounding box');
  }
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2, { steps: options.steps ?? 12 });
}
TS
  printf 'HUMAN_E2E_HELPER %s\n' "$file"
}

create_config_if_missing() {
  local config="$1"
  if [[ -n "$config" ]]; then
    printf 'HUMAN_E2E_CONFIG_EXISTS %s\n' "$config"
    printf 'HUMAN_E2E_ACTION Review and adapt existing config manually to preserve project conventions.\n'
    return 0
  fi

  cat > playwright.config.ts << 'TS'
import { defineConfig, devices } from '@playwright/test';

const recorded = process.env.HUMAN_E2E_RECORDED === '1';
const slowMo = Number(process.env.HUMAN_E2E_SLOWMO_MS ?? 0);
const browserName = process.env.HUMAN_E2E_BROWSER ?? 'chromium';

export default defineConfig({
  testDir: './tests/e2e',
  workers: recorded ? 1 : undefined,
  reporter: [['html', { outputFolder: process.env.PLAYWRIGHT_HTML_REPORT ?? 'playwright-report', open: 'never' }], ['list']],
  use: {
    headless: !recorded,
    screenshot: 'only-on-failure',
    trace: recorded ? 'on' : 'on-first-retry',
    video: recorded ? 'on' : 'retain-on-failure',
    launchOptions: { slowMo },
  },
  projects: [
    {
      name: browserName,
      use: browserName === 'chrome'
        ? { ...devices['Desktop Chrome'], channel: 'chrome' }
        : { ...devices['Desktop Chrome'], browserName: browserName as 'chromium' | 'firefox' | 'webkit' },
    },
  ],
});
TS
  printf 'HUMAN_E2E_CONFIG_CREATED playwright.config.ts\n'
}

main() {
  if [[ ! -f package.json ]]; then
    printf 'HUMAN_E2E_FAIL package.json not found. Run from a TypeScript project root.\n' >&2
    return 2
  fi

  local pm config
  pm="$(detect_pm)"
  config="$(find_playwright_config || true)"

  print_inspection "$pm" "$config"

  if [[ "$MODE" == "inspect" ]]; then
    return 0
  fi

  if ! has_dep '@playwright/test'; then
    printf 'HUMAN_E2E_INSTALL adding @playwright/test with %s\n' "$pm"
    pm_add_dev "$pm" '@playwright/test'
  fi

  printf 'HUMAN_E2E_INSTALL ensuring Playwright browsers with %s\n' "$pm"
  pm_playwright "$pm" install

  create_config_if_missing "$config"
  create_human_helper

  printf 'HUMAN_E2E_DONE setup complete. Review changes before running tests.\n'
}

main "$@"
