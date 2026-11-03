/*
 * CI/CD pipeline for the my-ai-apps monorepo (branch: dev02).
 *
 * The pipeline is intentionally self-contained:
 *   - it clones/fetches https://github.com/mujtabahussainjoo/my-ai-apps.git
 *   - it detects which top-level apps changed since the last successful build
 *   - it runs each app's quality gates inside Docker build containers
 *   - it optionally builds images and deploys deployable apps with Docker Compose
 *
 * The Jenkins controller does not need Python, Node, or uv installed. It only
 * needs the Docker CLI plus access to the host Docker socket (see
 * /var/www/html/docker/jenkins/Dockerfile and docker-compose.yml).
 */

def REPO = 'https://github.com/mujtabahussainjoo/my-ai-apps.git'
def BRANCH = 'dev02'
def APPS = ['ecom-bot', 'jail-break', 'my-exam', 'my-finance', 'my-pa', 'nexa-pilot-ai']
def DEPLOYABLE = ['ecom-bot', 'my-exam', 'my-finance', 'my-pa', 'nexa-pilot-ai']
def JENKINS_HOME = env.JENKINS_HOME ?: '/var/jenkins_home'
def STATE_DIR = "${JENKINS_HOME}/my-ai-apps-ci"
def LAST_FILE = "${STATE_DIR}/last-commit"
def HOST_WORKSPACE = params.HOST_WORKSPACE ?: '/var/www/html/docker/jenkins/home/workspace/my-ai-apps-ci'

def runInContainer(String image, String dir, String script) {
    writeFile file: "${dir}/.ci-step.sh", text: "#!/bin/sh\nset -eu\n${script}\n"
    sh """
        docker run --rm \
          -v '${HOST_WORKSPACE}:${env.WORKSPACE}' \
          -u \$(id -u):\$(id -g) \
          -e HOME=/tmp \
          -e npm_config_cache=/tmp/.npm \
          -e UV_CACHE_DIR=/tmp/uv-cache \
          -e ELECTRON_SKIP_BINARY_DOWNLOAD=1 \
          -w '${env.WORKSPACE}/${dir}' \
          ${image} sh ./.ci-step.sh
    """
}

def gateEcomBot() {
    runInContainer('python:3.12-slim', 'app/ecom-bot', '''
python -m pip install --user --quiet uv
export PATH="$HOME/.local/bin:$PATH"
uv sync --frozen
uv run ruff check .
uv run ruff format --check .
mkdir -p ci-reports
uv run pytest -q --junitxml=ci-reports/pytest.xml
''')
}

def gateJailBreak() {
    runInContainer('node:20-alpine', 'app/jail-break', '''
npm ci --no-audit --no-fund
npm run build
''')
}

def gateMyExam() {
    runInContainer('node:20-alpine', 'app/my-exam', '''
export DATABASE_URL="${DATABASE_URL:-postgresql://ci:ci@127.0.0.1:5432/ci}"
export SESSION_SECRET="${SESSION_SECRET:-ci-dummy-session-secret}"
npm ci --no-audit --no-fund
set +e
npm run lint
LINT_STATUS=$?
set -e
npm run build
if [ "$LINT_STATUS" -ne 0 ]; then
  echo "ESLint reported issues; see the log above."
  exit "$LINT_STATUS"
fi
''')
}

def gateMyFinance() {
    runInContainer('python:3.12-slim', 'app/my-finance', '''
python -m venv .ci-venv
. .ci-venv/bin/activate
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -e ".[dev]"
ruff check src apps scripts tests
ruff format --check src apps scripts tests
mkdir -p ci-reports
pytest -q --junitxml=ci-reports/pytest.xml
set +e
mypy src
MYPY_STATUS=$?
set -e
if [ "$MYPY_STATUS" -ne 0 ]; then
  echo "mypy reported issues (non-blocking)."
fi
''')
}

def gateMyPa() {
    runInContainer('python:3.12-slim', 'app/my-pa', '''
python -m venv .ci-venv
. .ci-venv/bin/activate
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -e . pytest
mkdir -p ci-reports
pytest -q --junitxml=ci-reports/pytest.xml
''')
}

def gateNexaPilot() {
    catchError(buildResult: 'UNSTABLE', stageResult: 'FAILURE') {
        runInContainer('python:3.12', 'app/nexa-pilot-ai/backend', '''
python -m pip install --user --quiet uv
export PATH="$HOME/.local/bin:$PATH"
uv sync --frozen
uv run ruff check src tests
uv run ruff format --check src tests
uv run mypy
mkdir -p ci-reports
uv run pytest -q --junitxml=ci-reports/pytest.xml
''')
    }
    catchError(buildResult: 'UNSTABLE', stageResult: 'FAILURE') {
        runInContainer('node:20-alpine', 'app/nexa-pilot-ai/frontend', '''
npm ci --no-audit --no-fund
npm run typecheck
npm test -- --run
npm run build
''')
    }
}

def runGate(String app) {
    switch (app) {
        case 'ecom-bot': gateEcomBot(); break
        case 'jail-break': gateJailBreak(); break
        case 'my-exam': gateMyExam(); break
        case 'my-finance': gateMyFinance(); break
        case 'my-pa': gateMyPa(); break
        case 'nexa-pilot-ai': gateNexaPilot(); break
        default: error("Unknown app: ${app}")
    }
}

timeout(time: 60, unit: 'MINUTES') {
    node {
        timestamps {
            try {
                stage('Checkout') {
                    sh """
                        set -eu
                        if [ -d app/.git ]; then
                          git -C app remote set-url origin '${REPO}'
                          git -C app fetch --prune origin '${BRANCH}'
                          git -C app reset --hard FETCH_HEAD
                          git -C app clean -fdx
                        else
                          rm -rf app
                          git clone --branch '${BRANCH}' --single-branch '${REPO}' app
                        fi
                        git -C app rev-parse HEAD > .ci-current-commit
                    """
                    env.CURRENT_COMMIT = readFile('.ci-current-commit').trim()
                    def last = sh(returnStdout: true, script: "cat '${LAST_FILE}' 2>/dev/null || true").trim()
                    env.LAST_COMMIT = last
                    echo "Repository : ${REPO}"
                    echo "Branch     : ${BRANCH}"
                    echo "Current    : ${env.CURRENT_COMMIT}"
                    echo "Last built : ${last ?: '(none)'}"
                }

                if (!params.FORCE_BUILD && env.LAST_COMMIT == env.CURRENT_COMMIT) {
                    echo "No new commit on ${BRANCH}; nothing to do."
                    return
                }

                def apps = []
                if (params.FORCE_BUILD || !env.LAST_COMMIT) {
                    apps = APPS
                } else {
                    def changed = sh(returnStdout: true, script: """
                        set -eu
                        if ! git -C app cat-file -e '${env.LAST_COMMIT}^{commit}' 2>/dev/null; then
                          echo ALL
                        elif ! git -C app diff --name-only '${env.LAST_COMMIT}' '${env.CURRENT_COMMIT}' > /tmp/changed.txt 2>/dev/null; then
                          echo ALL
                        else
                          cut -d/ -f1 /tmp/changed.txt | sort -u
                        fi
                    """).trim().readLines()
                    if (changed.contains('ALL')) {
                        apps = APPS
                    } else {
                        apps = APPS.findAll { changed.contains(it) }
                    }
                }

                if (apps.isEmpty()) {
                    echo "No application changes detected (docs/tooling only)."
                } else {
                    echo "Changed applications: ${apps.join(', ')}"
                    stage('Quality Gates') {
                        for (chunk in apps.collate(3)) {
                            def branches = [:]
                            for (app in chunk) {
                                def a = app
                                branches[a] = {
                                    catchError(buildResult: 'UNSTABLE', stageResult: 'FAILURE') {
                                        stage("Gate: ${a}") {
                                            runGate(a)
                                        }
                                    }
                                }
                            }
                            parallel branches
                        }
                    }
                }

                stage('Build Images') {
                    if (currentBuild.currentResult == 'SUCCESS') {
                        def toBuild = apps.findAll { DEPLOYABLE.contains(it) }
                        if (toBuild.isEmpty()) {
                            echo "No deployable apps changed; skipping image build."
                        } else {
                            echo "Building images for: ${toBuild.join(', ')}"
                            for (app in toBuild) {
                                switch (app) {
                                    case 'ecom-bot':
                                        sh "docker build -t myai-apps/ecom-bot:${env.BUILD_NUMBER} -t myai-apps/ecom-bot:dev02 app/ecom-bot"
                                        break
                                    case 'my-exam':
                                        sh "docker build -t myai-apps/my-exam:${env.BUILD_NUMBER} -t myai-apps/my-exam:dev02 app/my-exam"
                                        break
                                    case 'my-finance':
                                        sh "docker build -f app/my-finance/infrastructure/docker/Dockerfile --target api -t myai-apps/my-finance-api:${env.BUILD_NUMBER} -t myai-apps/my-finance-api:dev02 app/my-finance"
                                        sh "docker build -f app/my-finance/infrastructure/docker/Dockerfile --target worker -t myai-apps/my-finance-worker:${env.BUILD_NUMBER} -t myai-apps/my-finance-worker:dev02 app/my-finance"
                                        break
                                    case 'my-pa':
                                        sh "docker build -t myai-apps/my-pa:${env.BUILD_NUMBER} -t myai-apps/my-pa:dev02 app/my-pa"
                                        break
                                    case 'nexa-pilot-ai':
                                        sh "docker build -t myai-apps/nexa-backend:${env.BUILD_NUMBER} -t myai-apps/nexa-backend:dev02 app/nexa-pilot-ai/backend"
                                        sh "docker build -t myai-apps/nexa-frontend:${env.BUILD_NUMBER} -t myai-apps/nexa-frontend:dev02 app/nexa-pilot-ai/frontend"
                                        break
                                }
                            }
                        }
                    } else {
                        echo "Skipping image build because quality gates did not pass."
                    }
                }

                stage('Deploy') {
                    if (params.DEPLOY_TARGET != 'none' && currentBuild.currentResult == 'SUCCESS') {
                        echo "Deploying ${params.DEPLOY_TARGET}"
                        switch (params.DEPLOY_TARGET) {
                            case 'ecom-bot':
                                sh "docker compose -f app/ecom-bot/docker-compose.yml up -d"
                                break
                            case 'my-exam':
                                sh "docker compose -f app/my-exam/docker-compose.yml up -d"
                                break
                            case 'my-finance':
                                sh '''
                                    cat > app/my-finance/.env <<EOF
APP_ENV=development
API_KEY=ci-deploy-key
POSTGRES_USER=financ
POSTGRES_PASSWORD=financ
POSTGRES_DB=financ
POSTGRES_PORT=5432
REDIS_PORT=6380
API_PORT=8000
LLM_ENABLED=false
CORS_ORIGINS=http://localhost:8000
EOF
                                    docker compose -f app/my-finance/docker-compose.yml up -d postgres redis api
                                '''
                                break
                            case 'my-pa':
                                sh "docker run --rm myai-apps/my-pa:dev02"
                                break
                            case 'nexa-pilot-ai':
                                sh "docker compose -f app/nexa-pilot-ai/docker-compose.yml up -d"
                                break
                            default:
                                error("Unknown DEPLOY_TARGET: ${params.DEPLOY_TARGET}")
                        }
                    } else {
                        echo "Deploy skipped (DEPLOY_TARGET=${params.DEPLOY_TARGET}, result=${currentBuild.currentResult})."
                    }
                }
            } finally {
                junit allowEmptyResults: true, testResults: '**/ci-reports/*.xml'
                archiveArtifacts allowEmptyArchive: true, artifacts: '**/ci-reports/**', fingerprint: true
                if (env.CURRENT_COMMIT && (currentBuild.currentResult == 'SUCCESS' || currentBuild.currentResult == 'UNSTABLE')) {
                    sh "mkdir -p '${STATE_DIR}' && echo '${env.CURRENT_COMMIT}' > '${LAST_FILE}'"
                }
            }
        }
    }
}
