"""The function's side of Crossplane's protocol: what comes in the request, what goes out in
the response. The decisions are in connection.py and see plain dicts."""

from datetime import UTC, datetime

from crossplane.function import request, resource, response
from crossplane.function.proto.v1 import run_function_pb2 as fnv1
from crossplane.function.proto.v1 import run_function_pb2_grpc as grpcv1

from . import connection

# The version of each vendor's Device the composition reads, by the group deviceRef names.
DEVICES = {"iosxe.netclab.dev": "v1alpha1"}


class FunctionRunner(grpcv1.FunctionRunnerServiceServicer):
    async def RunFunction(
        self, req: fnv1.RunFunctionRequest, _context
    ) -> fnv1.RunFunctionResponse:
        rsp = response.to(req)

        # In: observed, as the cluster has it at the start of this pass.
        xr = numbers(resource.struct_to_dict(req.observed.composite.resource))
        composed = {
            name: numbers(resource.struct_to_dict(c.resource))
            for name, c in req.observed.resources.items()
        }
        namespace = xr["metadata"]["namespace"]

        # In: required, the Device and the user's Secrets; asked here, Crossplane fetches
        # them and calls again in the same pass.
        device_ref = xr["spec"]["customerGateway"]["deviceRef"]
        group = device_ref.get("apiGroup", "iosxe.netclab.dev")
        response.require_resources(
            rsp,
            name="device",
            api_version=f"{group}/{DEVICES[group]}",
            kind=device_ref.get("kind", "Device"),
            match_name=device_ref["name"],
            namespace=namespace,
        )
        device = request.get_required_resource(req, "device") or {}
        user_secrets = {}
        for spec in xr["spec"]["tunnels"]:
            name = spec["preSharedKeySecretRef"]["name"]
            response.require_resources(
                rsp,
                name=f"secret/{name}",
                api_version="v1",
                kind="Secret",
                match_name=name,
                namespace=namespace,
            )
            # a missing Secret is no key: the applied Secret stays, and Crossplane keeps it
            user_secrets[name] = (
                request.get_required_resource(req, f"secret/{name}") or {}
            )

        applied_keys, status, context = connection.decide(
            xr, composed, user_secrets, device, datetime.now(UTC)
        )

        # Out: desired, the applied Secret and the status; the context, for the templates.
        if applied_keys:
            resource.update(
                rsp.desired.resources["keys"],
                {
                    "apiVersion": "v1",
                    "kind": "Secret",
                    "type": "Opaque",
                    "metadata": {"name": context["keys"]["secret"]},
                    "data": applied_keys,
                },
            )
        resource.update_status(rsp.desired.composite, status)
        rsp.context.update({connection.CONTEXT: context})
        return rsp


def numbers(obj):
    """`obj` with every whole float an int again: a protobuf Struct holds numbers as doubles
    only, so awsTunnel 1 arrives as 1.0."""
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, float):
        return int(obj) if obj.is_integer() else obj
    if isinstance(obj, dict):
        return {key: numbers(value) for key, value in obj.items()}
    if isinstance(obj, list):
        return [numbers(value) for value in obj]
    return obj
