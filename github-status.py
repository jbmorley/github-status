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
import collections
import datetime
import itertools
import os.path
import pickle
import pprint
import sys
import time
import webbrowser

import dateutil.parser
import pytz
import requests
import tabulate
import termcolor
import yaml


SETTINGS_PATH = os.path.expanduser("~/.github-status")

CONFIGURATION_ENVIRONMENT_VARIABLE = "GITHUB_STATUS_CONFIGURATION"
CLIENT_ID_ENVIRONMENT_VARIABLE = "GITHUB_STATUS_CLIENT_ID"

if CONFIGURATION_ENVIRONMENT_VARIABLE in os.environ:
    CONFIGURATION_PATH = os.environ[CONFIGURATION_ENVIRONMENT_VARIABLE]
else:
    CONFIGURATION_PATH = os.path.expanduser("~/.github-status-configuration.yaml")
CLIENT_ID = os.environ[CLIENT_ID_ENVIRONMENT_VARIABLE]


class WorkflowRun(object):

    def __init__(self, details):
        self._details = details

    @property
    def repository(self):
        return self._details['head_repository']['full_name']

    @property
    def name(self):
        return self._details['name']

    @property
    def head_branch(self):
        return self._details['head_branch']

    @property
    def conclusion(self):
        return self._details['conclusion']

    @property
    def updated_at(self):
        return dateutil.parser.isoparse(self._details['updated_at'])

    @property
    def age(self):
        now = datetime.datetime.utcnow().replace(tzinfo=pytz.UTC)
        return now - self.updated_at

    @property
    def age_summary(self):
        summary = "%dd" % self.age.days
        if self.age > datetime.timedelta(days=30):
            return termcolor.colored(summary, "yellow")
        return summary

    @property
    def is_success(self):
        return self.conclusion == 'success'

    @property
    def is_failure(self):
        return self.conclusion == 'failure'

    @property
    def color(self):
        if self.is_success:
            return 'green'
        elif self.is_failure:
            return 'red'
        return 'yellow'

    @property
    def status(self):
        return termcolor.colored(self.repository, self.color, attrs=["reverse"])

    @property
    def html_url(self):
        return self._details["html_url"]


class Spinner(object):

    def __init__(self):
        self._iterator = itertools.cycle(['-', '\\', '|', '/'])

    def update(self):
        sys.stdout.write(next(self._iterator))
        sys.stdout.flush()
        sys.stdout.write('\b')


spinner = Spinner()


def merge_dicts(*dict_args):
    result = {}
    for dictionary in dict_args:
        result.update(dictionary)
    return result


def get_workflows(token, repository):
    spinner.update()
    url = f"https://api.github.com/repos/{repository}/actions/workflows"
    return requests.get(url, headers={'Accept': 'application/vnd.github.v3+json',
                                      'Authorization': f"token {token}"}).json()


def get_workflow_runs(token, repository):
    spinner.update()
    url = f"https://api.github.com/repos/{repository}/actions/runs"
    response = requests.get(url, headers={'Accept': 'application/vnd.github.v3+json',
                                          'Authorization': f"token {token}"}).json()
    workflow_runs = [WorkflowRun(workflow_run) for workflow_run in response['workflow_runs']]
    return workflow_runs

def get_filtered_workflow_runs(token, details):

    counts = collections.defaultdict(int)

    def filter(workflow_run):
        if "branches" in details and workflow_run.head_branch not in details["branches"]:
            return False
        if "workflows" in details and workflow_run.name not in details["workflows"]:
            return False
        counts[workflow_run.name] += 1
        if "limit" in details and counts[workflow_run.name] > details["limit"]:
            return False
        return True

    workflows = [workflow_run for workflow_run in get_workflow_runs(token, details["name"]) if filter(workflow_run)]

    # Double-check that we've seen at least one of each requested build.
    if "workflows" in details:
        for workflow in details["workflows"]:
            if workflow not in counts:
                exit("No runs for workflow '%s' for repository '%s'." % (workflow, details["name"]))

    return workflows


def authenticate():
    response = requests.post("https://github.com/login/device/code",
                             data={'client_id': 'c987946a3420d3a1f311', 'scope': 'workflow repo'},
                             headers={'Accept': 'application/vnd.github.v3+json'})
    details = response.json()
    if "error" in details:
        exit(details['error_description'])
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

DESCRIPTION = """
Display the status of your GitHub projects.

Quickly report on recent actions by passing the repository on the command-line:

    github-status inseven/fileaway

Multiple repositories can be collected into one report by passing each
repository as a new argument:

    github-status inseven/fileaway inseven/bookmarks inseven/symbolic

Configuration
-------------

If no command-line arguments are passed, Github Status will look for a
configuration file in `~/.github-status-configuration.yaml`, or in the location
specified in the `GITHUB_STATUS_CONFIGURATION` environment variable (if set).
"""


def main():
    parser = argparse.ArgumentParser(description=DESCRIPTION, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('repository', nargs='*', default=[])
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

    # Convert the command-line options into the richer configuration format.
    repositories = [{
            "name": repository,
            "branches": ["main", "master"],
            "limit": 1
        }
        for repository in options.repository]

    # Load the configuration if no repositories have been specified.
    try:
        if not repositories:
            with open(CONFIGURATION_PATH) as fh:
                configuration = yaml.load(fh, Loader=yaml.SafeLoader)
                for repository in configuration['repositories']:
                    repository = merge_dicts(configuration["defaults"] if "defaults" in configuration else {}, repository)
                    repositories.append(repository)
    except Exception as e:
        exit("Failed to load configuration with error '%s'." % e)

    workflow_runs = []
    for repository_details in repositories:
        workflow_runs.extend(get_filtered_workflow_runs(access_token, repository_details))
    workflow_runs.sort(key=lambda x: (x.repository, x.name, x.age))

    rows = [[workflow_run.status, workflow_run.name, workflow_run.age_summary, workflow_run.html_url]
            for workflow_run in workflow_runs]
    print(tabulate.tabulate(rows, headers=["Repository", "Workflow", "Age", "URL"]))


if __name__ == "__main__":
    main()
