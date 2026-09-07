
import os
from integration.helpers.validation_helpers import validate_all

def main():
    root = os.getcwd()
    data_in = os.path.join(root, "data", "in")
    data_out = os.path.join(root, "data", "out")
    
    print(f"Testing validation in: {data_in} -> {data_out}")
    results = validate_all(data_in, data_out, dry_run=False)
    
    print("\nValidation Results:")
    for check, res in results.items():
        status = "PASSED" if res["pass"] else "FAILED"
        print(f"{check}: {status} | {res['msg']}")

if __name__ == "__main__":
    main()
