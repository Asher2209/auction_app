# Production Deployment Checklist

## Pre-Deployment (Day Before)

### Environment Preparation
- [ ] `.env.production` created with all required variables
- [ ] Database backups tested and verified
- [ ] SSL certificates valid (not expiring within 30 days)
- [ ] All required ports open (80, 443)
- [ ] DNS records updated and propagated

### Security Review
- [ ] Secret key is random 32+ characters
- [ ] No hardcoded credentials in code
- [ ] Database encryption enabled
- [ ] API rate limiting configured
- [ ] CORS headers configured correctly
- [ ] HTTPS redirect enabled

### Infrastructure
- [ ] Server has 2+ GB free disk space
- [ ] Server has stable internet connection
- [ ] Database backup storage has 100+ GB free
- [ ] Monitoring and alerting configured
- [ ] Log rotation configured

### Testing
- [ ] Load tests passed (100 concurrent users)
- [ ] All unit tests passing
- [ ] Integration tests passing
- [ ] Payment flow tested end-to-end
- [ ] Blockchain verification tested

### Communication
- [ ] Stakeholders notified of deployment window
- [ ] Status page updated
- [ ] Support team briefed
- [ ] Rollback plan reviewed with team

---

## Deployment Day

### Pre-Deployment (30 min before)

**1. Final Health Check**
```bash
curl http://localhost:5000/api/health/ready
```
- [ ] All components healthy
- [ ] No errors in logs

**2. Database Backup**
```bash
./deployment/backup.sh
```
- [ ] Backup created successfully
- [ ] Backup size reasonable
- [ ] Backup compressed

**3. Current State Documentation**
```bash
git log --oneline -10
docker images | grep chainbid
```
- [ ] Current commit recorded
- [ ] Current image version recorded

### Deployment (execute deploy script)

```bash
cd /opt/chainbid
./deployment/deploy.sh
```

**Script does:**
- [ ] Pull latest code from repository
- [ ] Install dependencies
- [ ] Run database migrations
- [ ] Stop current application
- [ ] Start new application
- [ ] Verify application health

### Post-Deployment (15 min after)

**1. Health Verification**
```bash
# Readiness
curl http://localhost:5000/api/health/ready

# Liveness
curl http://localhost:5000/api/health/live

# Metrics
curl http://localhost:5000/api/health/metrics/summary
```
- [ ] Status 200 on all endpoints
- [ ] All components healthy
- [ ] No error alerts

**2. Functional Testing**
- [ ] Can browse auctions
- [ ] Can place bid
- [ ] Can create new auction
- [ ] Payment flow works
- [ ] Blockchain integration works

**3. Log Review**
```bash
tail -50 logs/app.log
tail -50 logs/blockchain_errors.log
tail -50 logs/transactions.log
```
- [ ] No critical errors
- [ ] No warnings in blockchain logs
- [ ] Normal transaction volume

**4. User Communication**
- [ ] Status page updated to "Operational"
- [ ] Deployment notification sent
- [ ] Support team confirmed ready

---

## If Deployment Fails

### Immediate Actions

```bash
./deployment/rollback.sh
```

**Rollback does:**
- [ ] Stop current application
- [ ] Restore previous backup
- [ ] Start application from backup
- [ ] Verify health

### Root Cause Analysis
- [ ] Check deployment logs
- [ ] Review error messages
- [ ] Identify which step failed
- [ ] Document the issue

### Communication
- [ ] Notify stakeholders of rollback
- [ ] Update status page
- [ ] Brief team on issue found

### Fix and Retry
- [ ] Fix the issue
- [ ] Re-test locally
- [ ] Schedule new deployment window
- [ ] Repeat deployment process

---

## Post-Deployment Monitoring (First 24 Hours)

### Every Hour
- [ ] Check error rate (should be < 1%)
- [ ] Monitor response times (should be < 500ms)
- [ ] Review transaction logs
- [ ] Check RPC latency

### Key Metrics to Watch
```
✓ Transaction success rate > 99%
✓ Average response time < 500ms
✓ Error rate < 1%
✓ RPC availability > 99.9%
✓ Blockchain confirmations < 5 minutes
```

### Alerts to Respond To
- [ ] Error rate > 5%
- [ ] RPC unavailable
- [ ] Database connection issues
- [ ] High response times

---

## Rollback Criteria

**Automatic rollback if:**
- Transaction success rate < 95%
- RPC unavailable for > 15 minutes
- Database corruption detected
- Critical security issue found
- Any complete system failure

**Decision to rollback:**
1. Detect issue
2. Consult with lead developer
3. Execute rollback within 5 minutes
4. Notify stakeholders
5. Begin root cause analysis

---

## Post-Deployment Sign-Off

### Day 1
- [ ] System stable
- [ ] No critical alerts
- [ ] Users reporting normal experience

### Day 7 (Final Review)
- [ ] Transaction volume normal
- [ ] Error rates stable and low
- [ ] Performance metrics good
- [ ] No user complaints
- [ ] All backups working

### Sign-Off
```
Deployment Date: _______________
Deployed By: _______________
Verified By: _______________
No Issues Found: ☐ Yes ☐ No
```

---

## Contacts

**In Case of Emergency:**
- Lead Dev: +1-XXX-XXX-XXXX
- DevOps: +1-XXX-XXX-XXXX
- On-Call: <on-call-rotation>

**Escalation:**
1. Try to fix within 30 minutes
2. Page on-call if not resolved
3. Alert VP Engineering if critical
4. If data loss risk: CEO approval for recovery

---

**Last Updated**: 2026-10-07
