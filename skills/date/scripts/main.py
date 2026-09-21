import sys
from datetime import date, timedelta


def main() -> None:
    args = sys.argv[1:]
    if not args:
        print(date.today().isoformat())
        return
    offset = int(args[0])
    print((date.today() + timedelta(days=offset)).isoformat())


if __name__ == "__main__":
    main()
