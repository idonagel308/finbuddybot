import urllib.request
import urllib.error
import time

def test_rate_limit_spoofing():
    url = "http://127.0.0.1:8000/summary/1983788745"
    api_key = "BZWwp_DClEDwXxTtR9yStme6W2OyUiGBZH5S2qUoJMw"
    
    # 1. Trigger the rate limit for IP 10.0.0.1
    print("Sending 60 requests for IP 10.0.0.1...")
    
    headers_10_0_0_1 = {
        "X-API-Key": api_key,
        "X-Forwarded-For": "10.0.0.1"
    }

    for i in range(65):
        req = urllib.request.Request(url, headers=headers_10_0_0_1)
        try:
            with urllib.request.urlopen(req) as response:
                pass # Success
        except urllib.error.HTTPError as e:
            if e.code == 429:
                print(f"Request {i+1} blocked by rate limit (429)! Expected for 10.0.0.1.")
                break
    else:
        print("Rate limit did not trigger for 10.0.0.1! Strange.")

    # 2. Try to access with a different IP. With the old code, this would be blocked too
    #    because the client.host is always 127.0.0.1.
    print("\nAttempting to connect with X-Forwarded-For: 10.0.0.2...")
    headers_10_0_0_2 = {
        "X-API-Key": api_key,
        "X-Forwarded-For": "10.0.0.2"
    }

    req = urllib.request.Request(url, headers=headers_10_0_0_2)
    try:
        with urllib.request.urlopen(req) as response:
            print(f"Request status: {response.getcode()} -> SUCCESS! (Proxy starvation prevented)")
    except urllib.error.HTTPError as e:
        print(f"Request status: {e.code} -> FAILED. Rate limiting might still be broken.")

if __name__ == "__main__":
    test_rate_limit_spoofing()
