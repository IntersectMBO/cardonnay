from cardonnay import helpers


class BColors:
    enable = helpers.should_use_color()

    HEADER = "\033[95m" if enable else ""
    OKBLUE = "\033[94m" if enable else ""
    OKCYAN = "\033[96m" if enable else ""
    OKGREEN = "\033[92m" if enable else ""
    WARNING = "\033[93m" if enable else ""
    FAIL = "\033[91m" if enable else ""
    ENDC = "\033[0m" if enable else ""
    BOLD = "\033[1m" if enable else ""
    UNDERLINE = "\033[4m" if enable else ""
