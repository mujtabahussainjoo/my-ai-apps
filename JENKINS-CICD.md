# Jenkins CI/CD Pipeline for `my-ai-apps` (`dev02`)

This document records the CI/CD setup built for the monorepo at
`/var/www/html/my-ai-apps` on branch `dev02`, using the Jenkins instance
running in Docker.

- Jenkins UI: <http://localhost:8082>
- Jenkins container: `jenkins` (image built locally as `my-jenkins:local`)
- Jenkins home on the host: `/var/www/html/docker/jenkins/home`
- Job name: `my-ai-apps-ci`
- Repository: <https://github.com/mujtabahussainjoo/my-ai-apps.git>
- Branch: `dev02`
- Poll interval: every minute (`* * * * *`)

---

## 1. What was built

A real pipeline job (`my-ai-apps-ci`) that:

1. Fetches `dev02` from GitHub.
2. Detects which top-level apps changed since the last completed build.
3. Runs each changed app's quality gates in isolated Docker containers.
4. Builds Docker images for the apps that have a `Dockerfile`.
5. Optionally deploys one of the deployable apps with Docker Compose.
6. Publishes JUnit reports and archives CI artifacts.
7. Remembers the last completed commit, so the one-minute poll exits quickly
   when nothing changed.

The Jenkins controller itself has no Python, Node, or `uv` installed. All
language toolchains run inside the build containers:

| App | Runtime container | Gates |
| --- | --- | --- |
| `ecom-bot` | `python:3.12-slim` | `uv sync --frozen`, Ruff lint + format check, pytest |
| `jail-break` | `node:20-alpine` | `npm ci`, TypeScript build |
| `my-exam` | `node:20-alpine` | `npm ci`, ESLint, Next.js production build |
| `my-finance` | `python:3.12-slim` | Ruff lint + format check, pytest, non-blocking mypy |
| `my-pa` | `python:3.12-slim` | editable install, pytest |
| `nexa-pilot-ai` | `python:3.12` + `node:20-alpine` | backend Ruff + mypy + pytest; frontend typecheck + vitest + build |

`my-buddy-app` is intentionally excluded: it is a nested, independent Git
repository that the parent repository ignores.

---

## 2. Architecture

```text
GitHub (mujtabahussainjoo/my-ai-apps, dev02)
        |
        |  every minute (Jenkins TimerTrigger)
        v
Jenkins controller (container: jenkins)
        |
        |  git fetch / git reset --hard
        v
/var/jenkins_home/workspace/my-ai-apps-ci/app
        |
        |  docker run --rm -v <workspace>:<workspace> ...
        v
+----------------+  +----------------+  +----------------+
| python:3.12    |  | node:20-alpine |  | python:3.12    |
| ecom-bot       |  | my-exam        |  | my-finance     |
+----------------+  +----------------+  +----------------+
        |                   |                   |
        +---------+---------+---------+---------+
                  |
                  v
        Docker daemon on the host
        (via /var/run/docker.sock)
```

The workspace is bind-mounted into build containers using the host path
parameter `HOST_WORKSPACE` (default
`/var/www/html/docker/jenkins/home/workspace/my-ai-apps-ci`). This avoids
mounting the Docker socket into the build containers themselves.

---

## 3. Files created and changed

### In the application repository (`/var/www/html/my-ai-apps`)

| File | Purpose |
| --- | --- |
| `Jenkinsfile` | Versioned copy of the pipeline. Use this if you later switch the job to "Pipeline script from SCM". |
| `JENKINS-CICD.md` | This document. |

> The running job currently uses an inline copy of the pipeline stored at
> `/var/www/html/docker/jenkins/home/my-ai-apps-ci/pipeline.groovy`. That is
> deliberate: it makes the pipeline work without requiring a push to `dev02`.
> The two files should be kept in sync.

### In the Docker/Jenkins host configuration (`/var/www/html/docker`)

| File | Change |
| --- | --- |
| `jenkins/Dockerfile` | New image based on `jenkins/jenkins:lts-jdk17` with `docker-cli`, `docker-compose`, `git`, `jq`, `make`, `curl`, and `unzip`. |
| `docker-compose.yml` | Jenkins now builds `my-jenkins:local`, mounts `/var/run/docker.sock`, and adds the host Docker group (`DOCKER_GID`). |
| `.env` / `.env.example` | Added `DOCKER_GID=1001` (matches `stat -c '%g' /var/run/docker.sock`). |
| `jenkins/home/init.groovy.d/20-my-ai-apps-ci.groovy` | Provisions/updates the `my-ai-apps-ci` job on every Jenkins startup. |
| `jenkins/home/my-ai-apps-ci/pipeline.groovy` | Inline pipeline source used by the job. |

---

## 4. Step-by-step setup that was performed

### Step 1 — Confirm the Jenkins container and Docker socket

```bash
docker ps --filter name=jenkins
stat -c '%g' /var/run/docker.sock
```

The socket group was `1001` (`docker`), and Jenkins runs as uid `1000`.

### Step 2 — Add Docker tooling to Jenkins

Created `/var/www/html/docker/jenkins/Dockerfile`:

```dockerfile
FROM jenkins/jenkins:lts-jdk17
USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates curl git jq make unzip \
        docker-cli docker-compose \
    && rm -rf /var/lib/apt/lists/*
USER jenkins
```

### Step 3 — Mount the Docker socket into Jenkins

Updated the `jenkins` service in `/var/www/html/docker/docker-compose.yml`:

```yaml
jenkins:
  build:
    context: ./jenkins
  image: my-jenkins:local
  volumes:
    - ./jenkins/home:/var/jenkins_home
    - /var/run/docker.sock:/var/run/docker.sock
  group_add:
    - "${DOCKER_GID:-1001}"
```

Added `DOCKER_GID=1001` to `/var/www/html/docker/.env`.

### Step 4 — Rebuild and recreate Jenkins

```bash
cd /var/www/html/docker
docker compose up -d --build jenkins
```

Verified:

```bash
docker exec jenkins docker --version
docker exec jenkins docker compose version
```

### Step 5 — Provision the pipeline job

Created `jenkins/home/init.groovy.d/20-my-ai-apps-ci.groovy`. On startup it:

- reads `jenkins/home/my-ai-apps-ci/pipeline.groovy`,
- creates or updates the `my-ai-apps-ci` Pipeline job,
- sets the parameters `FORCE_BUILD`, `DEPLOY_TARGET`, and `HOST_WORKSPACE`,
- disables concurrent builds,
- adds the one-minute `TimerTrigger` (`* * * * *`).

### Step 6 — Run the first build

```bash
# Get a CSRF crumb and keep the session cookie
CRUMB=$(curl -s -c /tmp/jenkins-cookies -u admin2:<password> \
  'http://localhost:8082/crumbIssuer/api/json' \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["crumb"])')

curl -s -b /tmp/jenkins-cookies -u admin2:<password> \
  -H "Jenkins-Crumb: $CRUMB" \
  -X POST 'http://localhost:8082/job/my-ai-apps-ci/buildWithParameters?FORCE_BUILD=false&DEPLOY_TARGET=none'
```

Or use the Jenkins UI: **my-ai-apps-ci → Build with Parameters → Build**.

---

## 5. Pipeline stages in detail

### Checkout

- Reuses the existing `app/` clone if present: `git fetch`, `git reset --hard
  FETCH_HEAD`, `git clean -fdx`.
- Otherwise clones `dev02` fresh.
- Records the current commit in `.ci-current-commit`.

### Change detection

Compares the current commit with the last completed commit stored in
`/var/jenkins_home/my-ai-apps-ci/last-commit`:

```bash
git diff --name-only <last> <current> | cut -d/ -f1 | sort -u
```

Only top-level directories that are in the known app list are built. If the
previous commit is unavailable (first build, force-push, or a shallow history),
all apps are built. Docs-only or tooling-only changes skip the app gates.

### Quality Gates

Changed apps run in parallel, three at a time (to stay within the host's
memory limits). Each app is wrapped in `catchError`:

- A failed gate marks that app's stage `FAILURE` and the overall build
  `UNSTABLE`.
- Remaining apps still run, so you get a complete report in one build.

### Build Images

Runs only when all quality gates passed and the app changed. Each image is
tagged with both the build number and `dev02`:

- `ecom-bot` → `myai-apps/ecom-bot:<build>` and `myai-apps/ecom-bot:dev02`
- `my-exam` → `myai-apps/my-exam:<build>` and `myai-apps/my-exam:dev02`
- `my-finance` → `myai-apps/my-finance-api:<build>`,
  `myai-apps/my-finance-api:dev02`, `myai-apps/my-finance-worker:<build>`, and
  `myai-apps/my-finance-worker:dev02`
- `my-pa` → `myai-apps/my-pa:<build>` and `myai-apps/my-pa:dev02`
- `nexa-pilot-ai` → `myai-apps/nexa-backend:<build>`,
  `myai-apps/nexa-backend:dev02`, `myai-apps/nexa-frontend:<build>`, and
  `myai-apps/nexa-frontend:dev02`

### Deploy (optional)

Controlled by the `DEPLOY_TARGET` parameter. Deployment only runs when the
build result is `SUCCESS`. The stage uses the `:dev02` image produced by
`Build Images`; if the selected app did not change in this build, it deploys the
existing `:dev02` image (use `FORCE_BUILD=true` to rebuild it first).

- `none` (default) — no deployment.
- `ecom-bot` — `docker compose -f app/ecom-bot/docker-compose.yml up -d`.
- `my-exam` — `docker compose -f app/my-exam/docker-compose.yml up -d`.
  Web UI on <http://localhost:3000>; Postgres is internal to the compose
  network.
- `my-finance` — writes `app/my-finance/.env` (CI-only credentials), then
  starts `postgres`, `redis`, and `api`:
  `docker compose -f app/my-finance/docker-compose.yml up -d postgres redis api`.
  API on <http://localhost:8000>.
- `my-pa` — smoke test only:
  `docker run --rm myai-apps/my-pa:dev02` (the CLI prints its help and exits).
- `nexa-pilot-ai` — `docker compose -f app/nexa-pilot-ai/docker-compose.yml up -d`.
  Web UI on <http://localhost:8080>; the frontend nginx proxies `/api/` to the
  backend on the compose network.

`jail-break` is not deployable (desktop app). `my-pa` is a CLI, so its deploy is
a smoke test rather than a long-running service.

The deploy stage uses the images built by the `Build Images` stage. The
`my-finance` deploy writes a `.env` with development-only values; replace it
with real secrets for a non-CI deployment.

> **Important:** the new `Dockerfile` and `docker-compose.yml` files in
> `my-exam`, `my-pa`, and `nexa-pilot-ai` (plus the `image:`/entrypoint fixes in
> `my-finance`) must be committed and pushed to `dev02`. The pipeline runs
> `git clean -fdx` after cloning, so untracked files are removed before the
> build starts.

To publish the deployment files:

```bash
git add Jenkinsfile JENKINS-CICD.md \
  ecom-bot/docker-compose.yml \
  my-finance/docker-compose.yml \
  my-finance/infrastructure/docker/Dockerfile \
  my-finance/infrastructure/docker/entrypoint.api.sh \
  my-finance/infrastructure/docker/entrypoint.worker.sh \
  my-exam/.dockerignore my-exam/Dockerfile my-exam/docker-compose.yml my-exam/docker-entrypoint.sh \
  my-pa/.dockerignore my-pa/Dockerfile \
  nexa-pilot-ai/docker-compose.yml \
  nexa-pilot-ai/backend/.dockerignore nexa-pilot-ai/backend/Dockerfile \
  nexa-pilot-ai/frontend/.dockerignore nexa-pilot-ai/frontend/Dockerfile nexa-pilot-ai/frontend/nginx.conf
git commit -m "ci: add deploy targets for all deployable apps"
git push origin dev02
```

The new images and compose files were also built and smoke-tested locally:

- `my-pa` — `mypa --help` exits 0.
- `my-exam` — the compose stack applies the schema and serves `/login` with
  HTTP 200.
- `my-finance` — the compose stack runs migrations, serves `/health/live` with
  HTTP 200, and starts the worker.
- `nexa-pilot-ai` — the backend reports healthy and the frontend nginx proxies
  `/api/health` with HTTP 200.
- `ecom-bot` — the image builds successfully.

### Reports

- JUnit: `**/ci-reports/*.xml`
- Archived artifacts: `**/ci-reports/**`

---

## 6. Parameters

| Parameter | Default | Meaning |
| --- | --- | --- |
| `FORCE_BUILD` | `false` | Run all app gates even when `dev02` has no new commit and no changed apps. |
| `DEPLOY_TARGET` | `none` | `none`, `ecom-bot`, `my-exam`, `my-finance`, `my-pa`, or `nexa-pilot-ai`. |
| `HOST_WORKSPACE` | `/var/www/html/docker/jenkins/home/workspace/my-ai-apps-ci` | Host path of the Jenkins workspace, bind-mounted into build containers. |

---

## 7. Real-time behaviour

The job has a Jenkins `TimerTrigger` with `* * * * *`, so it checks for new
commits every minute. Note: `H/1 * * * *` is **not** every minute — Jenkins
hashes it to one minute in the hour (for example, minute 0), so it polls only
once per hour. Use `* * * * *` (or `*/1 * * * *`) for true one-minute polling.
Each poll:

1. Fetches `dev02`.
2. Compares `HEAD` with the last completed commit.
3. Exits successfully in seconds if nothing changed.

This gives near-real-time CI without exposing Jenkins to the internet.

For true push-based triggering, add a GitHub webhook:

1. Expose Jenkins with a public HTTPS URL (for example, a Cloudflare Tunnel or
   ngrok).
2. In GitHub: **Settings → Webhooks → Add webhook**.
3. Payload URL: `https://<public-jenkins-url>/github-webhook/`
4. Content type: `application/json`
5. Event: **Just the push event**.

The `github` plugin is already installed. If you switch to a Multibranch
Pipeline later, the webhook also enables branch/PR discovery.

---

## 8. Switching to a versioned Jenkinsfile (recommended next step)

The current job uses the inline `pipeline.groovy` so it can run without
changing `dev02`. To move to the standard "Pipeline script from SCM" model:

1. Commit and push `Jenkinsfile` to `dev02`.
2. In Jenkins, open `my-ai-apps-ci → Configure`.
3. Change **Definition** to **Pipeline script from SCM**.
4. SCM: Git.
5. Repository URL: `https://github.com/mujtabahussainjoo/my-ai-apps.git`
6. Branch specifier: `*/dev02`
7. Script path: `Jenkinsfile`
8. Save.

After that, remove or disable
`jenkins/home/init.groovy.d/20-my-ai-apps-ci.groovy` so it does not overwrite
the job on restart.

---

## 9. Verified results (build #20, commit `294edaf`)

The pipeline was verified with a forced build (`FORCE_BUILD=true`) at commit
`294edaf73c105046977a0300a06d11e69231a6ea`. Build #20 started at 15:53:24 UTC
and finished at 15:59:37 UTC (about 6 minutes 13 seconds) with result
`UNSTABLE`. A normal timer poll with no new commit (build #2) finishes in about
14 seconds with `SUCCESS`.

| Gate | Result | Notes |
| --- | --- | --- |
| `ecom-bot` Ruff lint/format | pass | |
| `ecom-bot` pytest | fail | `tests/unit/test_health.py::test_ready_ok` returns `503` because no Postgres is reachable in the CI container. Integration tests skip for the same reason. |
| `jail-break` build | pass | |
| `my-exam` ESLint | fail | `react-hooks/set-state-in-effect` in `src/components/diagnostics-panel.tsx:59`. |
| `my-exam` build | pass | Next.js production build compiles. |
| `my-finance` Ruff check | pass | |
| `my-finance` Ruff format check | fail | `src/app.py` is not formatted (missing trailing newline after `# Your app code here`). pytest does not run after this failure. |
| `my-pa` pytest | pass | 57 tests pass. |
| `nexa-pilot-ai` backend | pass | Ruff, mypy, and 114 pytest tests pass. The `python:3.12` image is used because `python:3.12-slim` does not include `git`, which `tests/security/test_security.py::test_allowed_command_runs_without_a_shell` needs. |
| `nexa-pilot-ai` frontend typecheck | pass | |
| `nexa-pilot-ai` frontend vitest | fail | `src/lib/api.test.ts` → "rejects HTML from the wrong origin instead of returning null data": `TypeError: Body is unusable: Body has already been read`. `npm run build` does not run after the test failure. |

The overall build is `UNSTABLE` (yellow), not `SUCCESS` (green), because the
pipeline reports real app-level failures. Because at least one gate failed, the
Build Images stage was skipped and no images were produced; deployment was also
skipped (`DEPLOY_TARGET=none`). The backend and frontend gates for
`nexa-pilot-ai` are wrapped independently, so a backend failure no longer
prevents the frontend gate from running.

### Build #98 (after adding deploy targets)

After wiring the new `DEPLOY_TARGET` choices, build #98 (`FORCE_BUILD=true`,
`DEPLOY_TARGET=none`) re-ran all six apps and finished `UNSTABLE` in about
6 minutes 38 seconds with the same gate failures listed above. `Build Images`
and `Deploy` were skipped because the result was not `SUCCESS`. The new
parameter choices and pipeline were applied by restarting Jenkins; the job now
offers `none`, `ecom-bot`, `my-exam`, `my-finance`, `my-pa`, and
`nexa-pilot-ai`.

To get a green build, address these app-level issues:

1. Provide a Postgres service for `ecom-bot` (or mock the readiness check) so
   `test_ready_ok` and the integration tests can run.
2. Run `ruff format src/app.py` in `my-finance`.
3. Fix the `set-state-in-effect` ESLint error in `my-exam`.
4. Fix the `src/lib/api.test.ts` body-reuse bug in `nexa-pilot-ai/frontend`.

`my-finance` mypy is non-blocking and reports 66 existing errors.

---

## 10. Troubleshooting

### Jenkins cannot access Docker

```bash
docker exec jenkins id
docker exec jenkins docker ps
```

- Confirm `/var/run/docker.sock` is mounted.
- Confirm `DOCKER_GID` matches `stat -c '%g' /var/run/docker.sock`.
- Recreate the container after changing `DOCKER_GID`:

```bash
cd /var/www/html/docker
docker compose up -d --force-recreate jenkins
```

### Build containers cannot see the workspace

The `HOST_WORKSPACE` parameter must match the host path of the Jenkins
workspace. Verify with:

```bash
docker inspect jenkins --format '{{json .Mounts}}'
ls -ld /var/www/html/docker/jenkins/home/workspace/my-ai-apps-ci
```

### Permission denied writing `node_modules` or `.venv`

Build containers run as `-u 1000:1000` (the Jenkins uid/gid). The workspace
should be owned by uid `1000`. Check:

```bash
ls -ld /var/www/html/docker/jenkins/home/workspace/my-ai-apps-ci
```

### Job is not created after restart

Check the Jenkins log:

```bash
docker logs jenkins 2>&1 | grep -i 'my-ai-apps'
```

The init script prints `[my-ai-apps-ci] job provisioned.` when successful.

### Timer does not run every minute

Check the trigger spec in the job config:

```bash
grep -o '<spec>[^<]*</spec>' \
  /var/www/html/docker/jenkins/home/jobs/my-ai-apps-ci/config.xml
```

It must be `* * * * *`. `H/1 * * * *` is hashed to a single minute in the hour,
so the job appears to poll only once per hour. Update
`init.groovy.d/20-my-ai-apps-ci.groovy`, then restart Jenkins or update the
job definition.

### Force a rebuild

Use **Build with Parameters** and set `FORCE_BUILD=true`. This runs every app
gate even when `last-commit` equals the current commit. Without it, a build
with no new commit exits successfully in seconds. You can also delete the state
file:

```bash
rm -f /var/www/html/docker/jenkins/home/my-ai-apps-ci/last-commit
```

### Re-trigger the one-time first build

The init script uses a marker to schedule only one automatic first build:

```bash
rm -f /var/www/html/docker/jenkins/home/my-ai-apps-ci/.first-build-triggered
docker restart jenkins
```

---

## 11. Security notes

- Mounting `/var/run/docker.sock` gives the Jenkins controller (and anything
  that can run a pipeline) effective root access to the host. This is acceptable
  for a local development host but should be replaced with a dedicated Jenkins
  agent or rootless Docker in production.
- Build containers are trusted because they run code from `dev02`. Do not run
  this pipeline on untrusted pull requests.
- Do not commit real `.env` files or API keys. The pipeline uses dummy values
  for `my-exam` build-time environment variables.
- The Jenkins admin password is managed by
  `/var/www/html/docker/jenkins/home/init.groovy.d/reset.groovy`, outside this
  repository. Change it before exposing Jenkins beyond localhost.

---

## 12. Useful commands

```bash
# Jenkins status
docker ps --filter name=jenkins
docker logs -f jenkins

# Rebuild the Jenkins image after Dockerfile changes
cd /var/www/html/docker
docker compose up -d --build jenkins

# Read the latest build log without logging into the UI
# (replace 20 with the latest build number)
tail -f /var/www/html/docker/jenkins/home/jobs/my-ai-apps-ci/builds/20/log

# List images produced by the pipeline
docker images 'myai-apps/*'

# Check the last completed commit remembered by the pipeline
cat /var/www/html/docker/jenkins/home/my-ai-apps-ci/last-commit

# Trigger a build with parameters (replace <password>)
CRUMB=$(curl -s -c /tmp/jenkins-cookies -u admin2:<password> \
  'http://localhost:8082/crumbIssuer/api/json' \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["crumb"])')
curl -s -b /tmp/jenkins-cookies -u admin2:<password> \
  -H "Jenkins-Crumb: $CRUMB" \
  -X POST 'http://localhost:8082/job/my-ai-apps-ci/buildWithParameters?FORCE_BUILD=true&DEPLOY_TARGET=none'
```
