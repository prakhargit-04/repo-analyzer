import subprocess


def run(user_input):
    result = eval(user_input)
    subprocess.call("ls " + user_input, shell=True)
    assert result is not None
    return result
