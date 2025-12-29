# 🚀 CI/CD Pipeline Documentation

## Overview

This repository includes a comprehensive CI/CD pipeline that ensures code quality, runs automated tests, and deploys with confidence. The pipeline is built with GitHub Actions and follows enterprise best practices.

## 🔄 Workflows

### 1. **Continuous Integration** (`.github/workflows/ci.yml`)

Runs automatically on every push and pull request to validate code quality and functionality.

#### Triggers
- Push to `main` or `develop` branches
- Pull requests to `main`
- Manual workflow dispatch

#### Jobs
- **🔍 Code Quality & Linting** - Black, isort, flake8, mypy
- **🔒 Security Scanning** - Bandit security analysis
- **🧪 Testing Matrix** - Unit, integration, FTS, credits tests
- **🔄 E2E Tests** - Complete user journey validation
- **🏗️ Build Validation** - App startup and import checks
- **⚡ Performance Testing** - Benchmark execution

#### Coverage Requirements
- **80% minimum** code coverage
- **All test categories** must pass
- **No security vulnerabilities** detected

### 2. **Production Deployment** (`.github/workflows/deploy.yml`)

Handles safe deployment to staging and production environments with health checks.

#### Triggers
- Push to `main` branch (→ staging)
- Git tags `v*` (→ production)
- Manual workflow dispatch

#### Jobs
- **📋 Pre-Deployment Validation** - Environment checks
- **🗄️ Database Migrations** - Supabase schema updates
- **⚡ Edge Functions** - Deploy serverless functions
- **🚀 FastAPI App** - Main application deployment
- **🌐 Frontend** - React app deployment (if exists)
- **🔍 Health Checks** - Post-deployment validation

#### Environments
- **Staging**: Automatic on `main` branch
- **Production**: Manual approval + health checks

### 3. **Release Management** (`.github/workflows/release.yml`)

Manages versioned releases with automated changelog generation.

#### Triggers
- Git tags matching `v*` pattern
- Manual release creation

#### Features
- **📝 Automated changelogs** from commit messages
- **🏷️ Semantic versioning** support
- **📦 GitHub releases** with artifacts
- **🚀 Production deployment** integration
- **🔄 Rollback capabilities** on failure

## 🔧 Configuration

### Required Secrets

Configure these secrets in your GitHub repository settings:

#### Database & Backend
```bash
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_KEY=eyJhbGciOiJIUzI1NiIs...
DATABASE_URL=postgresql://postgres:...
```

#### API Keys
```bash
OPENAI_API_KEY=sk-proj-...
RAPIDAPI_KEY=...
```

#### Deployment
```bash
RENDER_DEPLOY_HOOK=https://api.render.com/deploy/...
APP_URL=https://your-app.com
PRODUCTION_URL=https://your-app.com
```

#### Optional Monitoring
```bash
MONITORING_URL=https://monitoring.your-app.com
SLACK_WEBHOOK=https://hooks.slack.com/...
```

### Environment Variables

Set these in your deployment environment:

```bash
# Core Application
NODE_ENV=production
PYTHON_ENV=production
LOG_LEVEL=INFO

# Feature Flags
ENABLE_E2E_TESTS=true
ENABLE_PERFORMANCE_TESTS=true
```

## 🧪 Testing Strategy

### Test Categories

| Category | Marker | Description | Coverage |
|----------|--------|-------------|----------|
| **Unit** | `@pytest.mark.unit` | Individual function testing | 90%+ |
| **Integration** | `@pytest.mark.integration` | Component interaction | 85%+ |
| **E2E** | `@pytest.mark.e2e` | Complete user flows | Key journeys |
| **FTS** | `@pytest.mark.fts` | Search functionality | All search features |
| **Credits** | `@pytest.mark.credits` | Payment/credit system | 100% |
| **SMS** | `@pytest.mark.sms` | SMS workflows | All flows |

### Test Execution

```bash
# Local development
python app/run_tests.py --coverage

# CI environment (automatic)
pytest --cov=. --cov-report=xml --parallel

# Specific categories
pytest -m "unit or integration"
pytest -m "e2e" --verbose
```

### Quality Gates

Before deployment, all jobs must pass:
- ✅ **Linting**: Black, isort, flake8 compliance
- ✅ **Security**: No bandit vulnerabilities  
- ✅ **Tests**: 80%+ coverage, all categories pass
- ✅ **Build**: App imports and starts successfully
- ✅ **Performance**: Benchmarks within thresholds

## 🚀 Deployment Process

### Automatic Deployments

1. **Development** → Push to `develop` → CI validation
2. **Staging** → Push to `main` → Deploy to staging
3. **Production** → Create release tag → Deploy to production

### Manual Deployments

1. **Navigate** to Actions tab
2. **Select** "Production Deployment"
3. **Click** "Run workflow"
4. **Choose** environment and options
5. **Monitor** deployment progress

### Health Checks

Post-deployment validation includes:
- **🔍 Health endpoint** - `/health` returns 200
- **🗄️ Database connectivity** - Supabase connection test
- **🌐 API endpoints** - Critical endpoints functional
- **⚡ Performance** - Response time < 2s

### Rollback Process

If deployment fails:
1. **Automatic notifications** alert team
2. **Health checks fail** → deployment marked failed
3. **Manual rollback** options provided
4. **Previous version** can be redeployed
5. **Hotfix process** available for critical issues

## 📊 Monitoring & Observability

### Deployment Metrics

Each deployment tracks:
- **Deployment time** and duration
- **Health check results** and response times
- **Test coverage** and pass rates
- **Performance benchmarks**

### Notifications

Configured notifications for:
- ✅ **Successful deployments**
- ❌ **Failed deployments** 
- ⚠️ **Health check failures**
- 📊 **Performance degradation**

### Dashboards

Monitor via:
- **GitHub Actions** - Workflow status and logs
- **Application logs** - Runtime monitoring
- **Database metrics** - Supabase dashboard
- **Performance metrics** - Response time tracking

## 🔒 Security & Compliance

### Security Scanning

Automatic security checks:
- **Bandit** - Python security linting
- **Dependency scanning** - Vulnerable packages
- **Secret detection** - Leaked credentials
- **Code analysis** - Security best practices

### Access Control

- **Branch protection** - Require PR reviews
- **Environment protection** - Production approval
- **Secret management** - GitHub secrets only
- **Audit logging** - All deployments tracked

### Compliance

- **Change tracking** - All deployments logged
- **Rollback capability** - Quick recovery
- **Health monitoring** - Continuous validation
- **Documentation** - Complete audit trail

## 🛠️ Troubleshooting

### Common Issues

#### CI Failures
```bash
# Linting errors
black app/ --check  # Check formatting
isort app/ --check  # Check imports

# Test failures  
python app/run_tests.py --verbose --pdb  # Debug tests

# Build issues
python -c "from app import app; print('OK')"  # Test imports
```

#### Deployment Failures
```bash
# Health check failures
curl https://your-app.com/health  # Test endpoint

# Database issues
python -c "from database import supabase; print(supabase)"  # Test connection

# Migration issues
supabase db push --dry-run  # Preview migrations
```

#### Performance Issues
```bash
# Test response times
time curl https://your-app.com/health

# Database performance
SELECT * FROM pg_stat_activity;  # Check active queries

# Application metrics
tail -f /var/log/app.log  # Check application logs
```

### Getting Help

1. **Check workflow logs** in GitHub Actions
2. **Review error messages** and stack traces
3. **Test locally** to reproduce issues
4. **Check documentation** for configuration
5. **Contact team** if issues persist

## 📈 Continuous Improvement

### Metrics to Track

- **Deployment frequency** - How often we deploy
- **Lead time** - Code to production time
- **Change failure rate** - % of deployments that fail
- **Recovery time** - Time to fix failed deployments

### Optimization Opportunities

- **Parallel test execution** - Reduce CI time
- **Incremental deployments** - Blue/green strategy
- **Performance monitoring** - Proactive optimization
- **Automated rollbacks** - Faster recovery

---

## 🎯 Success Criteria

Your CI/CD pipeline is successful when:
- ✅ **Every commit** is automatically tested
- ✅ **Deployments are safe** with health checks
- ✅ **Quality gates** prevent bad code from shipping
- ✅ **Rollbacks are fast** when issues occur
- ✅ **Team is confident** to deploy frequently

**Deploy fast, deploy safe, deploy with confidence! 🚀**