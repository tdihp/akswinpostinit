# AKSWINPOSTINIT -- AKS Windows node post provisioning initialization

## Features

This is a tool that provides one-time powershell script initilization for Windows node. 

1. Block scheduling using taint before initialization finished.
2. Optional reboot.
3. Customizable powershell script for initialization via runcommand.

## Controller Installation

See deploy_example.yaml for how to configure a yaml installation

## As a command line tool

### Prepare environment

Dev and command line environment can be prepared with below steps given a full git repository and Internet access.

    virtuanenv env
    source env/bin/activate
    pip install -r requirements.txt
    python -m akswinpostinit --version

### Run controller in command line

The controller can be run in command line given:

1. The kubectl context is properly configured in kubeconfig.
2. azure-cli login is done and can operate on the target virtual machines

To run the controller:

    python -m akswinpostinit --subscription <sub-of-cluster> -v

### Cleanup

Cleanup is also provided as a part of the script, to remove all annotation, taint and condition from nodes. It can be used to remove previous state in situation such as when a re-run is needed.

To clean up, first stop the controller, then:

    python -m akswinpostinit --cleanup
