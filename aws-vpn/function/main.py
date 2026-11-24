"""Serve the function over gRPC, with the SDK's standard options.

Crossplane sets TLS_SERVER_CERTS_DIR in the cluster. Run locally for `crossplane render`:

    uv run aws-vpn-function --insecure --debug     # listens on :9443
"""

import click
from crossplane.function import cli as sdkcli

from .fn import FunctionRunner


@click.command()
@sdkcli.standard_options
def main(**kwargs) -> None:
    sdkcli.run(FunctionRunner(), **kwargs)


if __name__ == "__main__":
    main()
