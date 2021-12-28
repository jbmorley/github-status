#!/usr/bin/env python3

# Copyright (c) 2021 Jason Morley
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

import argparse
import os.path
import pickle
import pprint
import time
import webbrowser

import requests
import termcolor


SETTINGS_PATH = os.path.expanduser("~/.github-status")
CLIENT_ID = os.environ["GITHUB_STATUS_CLIENT_ID"]


def get_workflows(token, repository):
    url = f"https://api.github.com/repos/{repository}/actions/workflows"
    return requests.get(url, headers={'Accept': 'application/vnd.github.v3+json',
                                      'Authorization': f"token {token}"}).json()


def get_runs(token, repository):
    url = f"https://api.github.com/repos/{repository}/actions/runs"
    return requests.get(url, headers={'Accept': 'application/vnd.github.v3+json',
                                      'Authorization': f"token {token}"}).json()


def authenticate():
    response = requests.post("https://github.com/login/device/code",
                             data={'client_id': 'c987946a3420d3a1f311', 'scope': 'workflow repo'},
                             headers={'Accept': 'application/vnd.github.v3+json'})
    details = response.json()
    webbrowser.open(details['verification_uri'])

    print(details['user_code'])
    device_code = details['device_code']
    interval = details['interval']

    print("Checking authentication status...")
    while True:
        time.sleep(interval)
        response = requests.post("https://github.com/login/oauth/access_token",
                         data={'client_id': CLIENT_ID,
                               'device_code': device_code,
                               'grant_type': 'urn:ietf:params:oauth:grant-type:device_code'},
                         headers={'Accept': 'application/vnd.github.v3+json'}).json()
        try:
            access_token = response['access_token']
            break
        except KeyError:
            pass

    return access_token


def color(workflow_run):
    if workflow_run['conclusion'] is None:
        return 'yellow'
    elif workflow_run['conclusion'] == 'success':
        return 'green'
    elif workflow_run['conclusion'] == 'failure':
        return 'red'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('repository', nargs='+')
    options = parser.parse_args()

    access_token = None
    if os.path.exists(SETTINGS_PATH):
        with open(SETTINGS_PATH, "rb") as fh:
            config = pickle.load(fh)
        access_token = config["access_token"]
    if access_token is None:
        access_token = authenticate()
        with open(SETTINGS_PATH, "wb") as fh:
            pickle.dump( {"access_token": access_token}, fh)

    for repository in sorted(options.repository):
        runs = get_runs(access_token, repository)
        workflow_runs = [workflow_run for workflow_run in runs['workflow_runs']
                         if workflow_run['head_branch'] == 'main' or workflow_run['head_branch'] == 'master']
        workflow_run = workflow_runs[0]
        conclusion = workflow_run['conclusion']
        termcolor.cprint("https://github.com/" + repository, color(workflow_run))


if __name__ == "__main__":
    main()
