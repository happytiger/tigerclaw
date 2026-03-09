"""Message bus module for decoupled channel-agent communication."""

from tigerclaw.bus.events import InboundMessage, OutboundMessage
from tigerclaw.bus.queue import MessageBus

__all__ = ["MessageBus", "InboundMessage", "OutboundMessage"]
