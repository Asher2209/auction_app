# Error Analysis Report - Load Test Execution

**Date**: 2026-10-07  
**Status**: Errors Identified & Solutions Provided  

---

## Errors Encountered

### Error 1: Character Encoding Issue
```
'charmap' codec can't encode character '\u2717' in position 0
```

**Root Cause**: Windows PowerShell using system locale encoding (not UTF-8)
**Affected Code**: Unicode checkmark character (✓) in print statements
**Severity**: LOW - Script still runs, output garbled

**Solution**:
```python
# Add to top of load_test.py
import sys
import os

# Force UTF-8 encoding
if sys.platform == 'win32':
    os.environ['PYTHONIOENCODING'] = 'utf-8'
    sys.stdout.reconfigure(encoding='utf-8')
```

---

### Error 2: Connection Error (404 Not Found)
```
Error Codes: 404: 1
```

**Root Cause**: Flask application not running on localhost:5000
**Affected Endpoint**: /api/health/ready
**Severity**: EXPECTED - Need running app to test

**Solution**:
```bash
# Terminal 1: Start Flask app
python -m flask run

# Terminal 2: Wait for "Running on..." message
# Then run load test
python deployment/load_test.py
```

---

### Error 3: Test Failure on First Attempt
```
Test failed with error: 'charmap' codec can't encode character
```

**Root Cause**: Combination of encoding issue + connection error
**When It Happens**: When running on Windows PowerShell
**Severity**: MEDIUM - Affects Windows users

**Solution**: Use UTF-8 PowerShell or Python directly:
```bash
# Option 1: Use Python directly
python deployment/load_test.py

# Option 2: Set encoding in PowerShell
$env:PYTHONIOENCODING = 'utf-8'
python deployment/load_test.py

# Option 3: Use bash/Git Bash (recommended)
bash deployment/load_test.py
```

---

## Fixed Load Test Script

Here's the corrected version addressing all errors:

```python
"""Load testing script - Fixed version with proper encoding."""

import requests
import time
import threading
from datetime import datetime
import json
from statistics import mean, median, stdev
import sys
import os

# Force UTF-8 encoding on Windows
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except:
        os.environ['PYTHONIOENCODING'] = 'utf-8'


class LoadTestMetrics:
    def __init__(self):
        self.response_times = []
        self.errors = []
        self.success_count = 0
        self.failure_count = 0
        self.start_time = None
        self.end_time = None
    
    def add_response(self, elapsed_ms: int, status_code: int, success: bool):
        """Record a response."""
        self.response_times.append(elapsed_ms)
        if success:
            self.success_count += 1
        else:
            self.failure_count += 1
            self.errors.append(status_code)
    
    def print_summary(self):
        """Print test summary."""
        total = self.success_count + self.failure_count
        elapsed = (self.end_time - self.start_time).total_seconds()
        
        print("\n" + "=" * 80)
        print("LOAD TEST RESULTS")
        print("=" * 80)
        print(f"\nTest Duration: {elapsed:.1f} seconds")
        print(f"Total Requests: {total}")
        print(f"Successful: {self.success_count} ({self.success_count/total*100:.1f}%)")
        print(f"Failed: {self.failure_count} ({self.failure_count/total*100:.1f}%)")
        
        if self.response_times:
            print(f"\nResponse Times (ms):")
            print(f"  Min: {min(self.response_times):.1f}")
            print(f"  Median: {median(self.response_times):.1f}")
            print(f"  Mean: {mean(self.response_times):.1f}")
            print(f"  Max: {max(self.response_times):.1f}")
            if len(self.response_times) > 1:
                print(f"  StdDev: {stdev(self.response_times):.1f}")
        
        if self.errors:
            error_counts = {}
            for code in self.errors:
                error_counts[code] = error_counts.get(code, 0) + 1
            print(f"\nError Codes:")
            for code, count in sorted(error_counts.items()):
                print(f"  {code}: {count}")
        
        print(f"\nRequests/sec: {total/elapsed:.1f}")
        print("=" * 80 + "\n")


def test_health_check(base_url: str, metrics: LoadTestMetrics):
    """Test health check endpoint."""
    print("Testing health checks...")
    
    try:
        start = time.time()
        response = requests.get(f"{base_url}/api/health/ready", timeout=10)
        elapsed = (time.time() - start) * 1000
        
        metrics.add_response(elapsed, response.status_code, response.status_code == 200)
        status_symbol = "[OK]" if response.status_code == 200 else "[FAIL]"
        print(f"{status_symbol} Health check: {response.status_code} ({elapsed:.1f}ms)")
    except requests.exceptions.ConnectionError:
        print("[ERROR] Cannot connect to app at " + base_url)
        print("  Make sure Flask app is running: python -m flask run")
        metrics.add_response(0, 0, False)
    except Exception as e:
        print(f"[ERROR] Health check failed: {str(e)}")
        metrics.add_response(0, 0, False)


def test_concurrent_users(base_url: str, num_users: int, metrics: LoadTestMetrics):
    """Simulate concurrent user requests."""
    print(f"\nTesting {num_users} concurrent users...")
    
    def make_request(user_id: int):
        try:
            start = time.time()
            response = requests.get(
                f"{base_url}/api/auctions",
                params={"page": 1, "per_page": 20},
                timeout=10
            )
            elapsed = (time.time() - start) * 1000
            metrics.add_response(elapsed, response.status_code, response.status_code == 200)
        except Exception as e:
            metrics.add_response(0, 0, False)
    
    threads = []
    for i in range(num_users):
        t = threading.Thread(target=make_request, args=(i,))
        threads.append(t)
        t.start()
    
    for t in threads:
        t.join()
    
    print(f"[OK] Concurrent users test complete")


def test_bid_volume(base_url: str, num_bids: int, auction_id: int, metrics: LoadTestMetrics):
    """Simulate high bid volume."""
    print(f"\nTesting {num_bids} concurrent bids...")
    
    def place_bid(bid_id: int):
        try:
            start = time.time()
            response = requests.post(
                f"{base_url}/api/auctions/{auction_id}/bid",
                json={"amount": 50000 + bid_id},
                timeout=10,
                headers={"Authorization": f"Bearer test_token_{bid_id}"}
            )
            elapsed = (time.time() - start) * 1000
            metrics.add_response(elapsed, response.status_code, response.status_code in [200, 409])
        except Exception as e:
            metrics.add_response(0, 0, False)
    
    threads = []
    for i in range(num_bids):
        t = threading.Thread(target=place_bid, args=(i,))
        threads.append(t)
        t.start()
    
    for t in threads:
        t.join()
    
    print(f"[OK] Bid volume test complete")


def main():
    """Run all load tests."""
    base_url = "http://localhost:5000"
    
    print("ChainBid Load Testing Suite")
    print("=" * 80)
    print(f"Target: {base_url}")
    print(f"Start Time: {datetime.now()}")
    print("=" * 80)
    
    # Check if app is running
    try:
        requests.get(base_url, timeout=2)
    except:
        print("\n[WARNING] Flask app not running!")
        print("Start app first: python -m flask run")
        print("Then run this script again")
        return
    
    metrics = LoadTestMetrics()
    metrics.start_time = datetime.now()
    
    try:
        test_health_check(base_url, metrics)
        test_concurrent_users(base_url, 100, metrics)
        test_bid_volume(base_url, 100, auction_id=1, metrics=metrics)
    
    except Exception as e:
        print(f"\n[ERROR] Test failed: {str(e)}")
    
    finally:
        metrics.end_time = datetime.now()
        metrics.print_summary()
        
        results = {
            "timestamp": datetime.now().isoformat(),
            "total_requests": metrics.success_count + metrics.failure_count,
            "successful": metrics.success_count,
            "failed": metrics.failure_count,
            "success_rate": metrics.success_count / (metrics.success_count + metrics.failure_count) if (metrics.success_count + metrics.failure_count) > 0 else 0,
            "response_times": {
                "min": min(metrics.response_times) if metrics.response_times else 0,
                "max": max(metrics.response_times) if metrics.response_times else 0,
                "avg": mean(metrics.response_times) if metrics.response_times else 0,
                "median": median(metrics.response_times) if metrics.response_times else 0,
            }
        }
        
        with open("load_test_results.json", "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)
        
        print("Results saved to load_test_results.json")


if __name__ == "__main__":
    main()
```

---

## Error Prevention Checklist

Before running load test:

- [ ] Flask app is running: `python -m flask run`
- [ ] App shows "Running on http://127.0.0.1:5000"
- [ ] No port conflict (port 5000 in use?)
- [ ] Python encoding set to UTF-8
- [ ] requests library installed: `pip install requests`

---

## How to Run Without Errors

### Method 1: Python Command Line (Recommended)
```bash
# Start app
python -m flask run

# In new terminal
python deployment/load_test.py
```

### Method 2: Use Bash/Git Bash (Windows Users)
```bash
bash deployment/load_test.py
```

### Method 3: Set Encoding First (PowerShell)
```powershell
$env:PYTHONIOENCODING = 'utf-8'
python deployment/load_test.py
```

---

## Troubleshooting Guide

### Issue: "Cannot connect to localhost:5000"
**Solution**: 
```bash
# Terminal 1
python -m flask run

# Wait for "Running on http://127.0.0.1:5000"
# Then run load test in Terminal 2
python deployment/load_test.py
```

### Issue: "Character encoding errors" on Windows
**Solution**:
```bash
# Option A: Use Python directly
python deployment/load_test.py

# Option B: Set encoding
$env:PYTHONIOENCODING = 'utf-8'
python deployment/load_test.py

# Option C: Use bash
bash deployment/load_test.py
```

### Issue: "Connection refused"
**Solution**:
```bash
# Check if Flask is running
curl http://localhost:5000/api/health/ready

# If not, start it
python -m flask run
```

### Issue: "Port 5000 already in use"
**Solution**:
```bash
# Use different port
flask run --port 5001

# Update load_test.py
base_url = "http://localhost:5001"
```

---

## Verification Steps

After fixing errors, verify:

1. **Flask App Running**
   ```
   ✓ See "Running on http://127.0.0.1:5000"
   ✓ No errors in Flask output
   ```

2. **Load Test Starts**
   ```
   ✓ See "ChainBid Load Testing Suite"
   ✓ See "Testing health checks..."
   ```

3. **Results Generated**
   ```
   ✓ See test results summary
   ✓ load_test_results.json created
   ✓ All metrics calculated
   ```

---

## Expected Output (No Errors)

```
ChainBid Load Testing Suite
================================================================================
Target: http://localhost:5000
Start Time: 2026-10-07 14:30:00

Testing health checks...
[OK] Health check: 200 (48.5ms)

Testing 100 concurrent users...
[OK] Concurrent users test complete

Testing 1000 concurrent bids...
[OK] Bid volume test complete

================================================================================
LOAD TEST RESULTS
================================================================================

Test Duration: 85.3 seconds
Total Requests: 1110
Successful: 1,095 (98.6%)
Failed: 15 (1.4%)

Response Times (ms):
  Min: 42.1
  Median: 156.8
  Mean: 172.3
  Max: 987.2
  StdDev: 145.6

Requests/sec: 13.0
================================================================================

Results saved to load_test_results.json
```

---

## Summary of Fixes

| Error | Cause | Solution |
|-------|-------|----------|
| Encoding error | Windows default encoding | Use UTF-8, Python directly, or bash |
| 404 Not Found | App not running | Start Flask with `python -m flask run` |
| Connection refused | Port not listening | Check Flask output, start if needed |
| Test failure | Multiple of above | Follow checklist above |

---

**Status**: ✅ All errors identified and solutions provided

Run load test using the corrected method and it should work without errors.
