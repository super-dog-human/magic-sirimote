"""Serialize cooperating project feature users, not arbitrary TV software."""
from supervisor_lease import SupervisorLease

class LocalFeatureLease(SupervisorLease):
 NAME='feature-control.lock'
