"""Load testing script for ChainBid auction system - FIXED VERSION.

Fixes applied:
- UTF-8 encoding for Windows compatibility
- Better error messages
- Pre-flight connection check
- Graceful error handling
"""

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
    except Exception:
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
        self.response_times.append(elapsed_ms)
        if success:
            self.success_count += 1
        else:
            self.failure_count += 1
            self.errors.append(status_code)
    
    def print_summary(self):
        total = self.success_count + self.failure_count
        if total == 0:
            print("[ERROR] No requests completed")
            return
        
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


def check_app_running(base_url: str) -> bool:
    """Check if Flask app is running."""
    try:
        response = requests.get(base_url, timeout=2)
        return True
    except requests.exceptions.ConnectionError:
        return False
    except Exception:
        return False


def test_health_check(base_url: str, metrics: LoadTestMetrics):
    """Test health check endpoint."""
    print("Testing health checks...")
    
    try:
        start = time.time()
        response = requests.get(f"{base_url}/api/health/ready", timeout=10)
        elapsed = (time.time() - start) * 1000
        
        metrics.add_response(elapsed, response.status_code, response.status_code == 200)
        status = "PASS" if response.status_code == 200 else "FAIL"
        print(f"  [{status}] Health check: {response.status_code} ({elapsed:.1f}ms)")
    except requests.exceptions.ConnectionError as e:
        print(f"  [ERROR] Cannot connect to {base_url}")
        metrics.add_response(0, 0, False)
    except requests.exceptions.Timeout:
        print(f"  [ERROR] Request timeout")
        metrics.add_response(0, 0, False)
    except Exception as e:
        print(f"  [ERROR] {str(e)}")
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
        except Exception:
            metrics.add_response(0, 0, False)
    
    threads = []
    for i in range(num_users):
        t = threading.Thread(target=make_request, args=(i,))
        threads.append(t)
        t.start()
    
    for t in threads:
        t.join()
    
    print(f"  [PASS] Concurrent users test complete")


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
        except Exception:
            metrics.add_response(0, 0, False)
    
    threads = []
    for i in range(num_bids):
        t = threading.Thread(target=place_bid, args=(i,))
        threads.append(t)
        t.start()
    
    for t in threads:
        t.join()
    
    print(f"  [PASS] Bid volume test complete")


def main():
    """Run all load tests."""
    base_url = "http://localhost:5000"
    
    print("ChainBid Load Testing Suite")
    print("=" * 80)
    print(f"Target: {base_url}")
    print(f"Start Time: {datetime.now()}")
    print("=" * 80)
    
    # Check if app is running
    print("\nPre-flight check...")
    if not check_app_running(base_url):
        print(f"\n[ERROR] Flask app not running at {base_url}")
        print("\nTo start Flask app, run in a separate terminal:")
        print("  python -m flask run")
        print("\nThen run this script again.")
        return
    
    print(f"[PASS] Flask app is running")
    
    metrics = LoadTestMetrics()
    metrics.start_time = datetime.now()
    
    try:
        test_health_check(base_url, metrics)
        test_concurrent_users(base_url, 100, metrics)
        test_bid_volume(base_url, 100, auction_id=1, metrics=metrics)
    
    except KeyboardInterrupt:
        print("\n[WARNING] Test interrupted by user")
    except Exception as e:
        print(f"\n[ERROR] Test failed: {str(e)}")
    
    finally:
        if metrics.start_time:
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
