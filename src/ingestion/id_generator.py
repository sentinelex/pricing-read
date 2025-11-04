"""
Dual ID generation for pricing components.
Implements semantic ID (stable logical identity) and instance ID (unique per snapshot).
"""
import hashlib
from typing import Dict


class IDGenerator:
    """Generates dual IDs for pricing components"""

    @staticmethod
    def generate_semantic_id(
        order_id: str,
        component_type: str,
        dimensions: Dict[str, str],
        refund_id: str = None
    ) -> str:
        """
        Generate stable semantic ID from logical dimensions.

        Format (regular): cs-{order_id}-{dimensions in canonical order}-{component_type}
        Format (refund): cs-{order_id}-{refund_id}-{dimensions in canonical order}-{component_type}

        Example regular: cs-ORD-9001-OD-001-A1-CGK-SIN-BaseFare
        Example refund: cs-ORD-9001-REF-001-OD-001-A1-CGK-SIN-BaseFare

        This ID stays constant across repricing, refunds, or lifecycle changes.
        For refund components, including refund_id ensures uniqueness.
        """
        # Sort dimensions for canonical ordering
        sorted_dims = sorted(dimensions.items())

        # Build dimension string
        dim_parts = []
        for key, value in sorted_dims:
            # Abbreviate common keys
            key_abbrev = {
                'order_detail_id': 'OD',
                'pax_id': 'P',
                'leg_id': 'L',
                'night_id': 'N',
                'room_id': 'R',
                'segment_id': 'S'
            }.get(key, key.upper()[:3])

            dim_parts.append(f"{key_abbrev}-{value}")

        # Construct semantic ID
        dimension_str = "-".join(dim_parts) if dim_parts else "ORDER"

        # For refund components, include refund_id in the semantic ID
        if refund_id:
            semantic_id = f"cs-{order_id}-{refund_id}-{dimension_str}-{component_type}"
        else:
            semantic_id = f"cs-{order_id}-{dimension_str}-{component_type}"

        return semantic_id

    @staticmethod
    def generate_instance_id(
        semantic_id: str,
        pricing_snapshot_id: str
    ) -> str:
        """
        Generate unique instance ID for a specific snapshot.

        Format: ci_{hash(semantic_id + snapshot_id)[:16]}
        Example: ci_f0a1d2c3b4a50001

        This ID is unique per occurrence in a pricing snapshot.
        """
        # Combine semantic ID and snapshot ID
        combined = f"{semantic_id}|{pricing_snapshot_id}"

        # Hash to get deterministic ID
        hash_obj = hashlib.sha256(combined.encode())
        hash_hex = hash_obj.hexdigest()[:16]

        return f"ci_{hash_hex}"

    @staticmethod
    def generate_dual_ids(
        order_id: str,
        component_type: str,
        dimensions: Dict[str, str],
        pricing_snapshot_id: str,
        refund_id: str = None
    ) -> Dict[str, str]:
        """
        Generate both semantic and instance IDs at once.

        Args:
            order_id: The order ID
            component_type: Type of component (e.g., BaseFare, Tax, Markup)
            dimensions: Component dimensions (order_detail_id, pax_id, etc.)
            pricing_snapshot_id: The pricing snapshot ID
            refund_id: Optional refund ID for refund components

        Returns:
            {
                'component_semantic_id': 'cs-...',
                'component_instance_id': 'ci_...'
            }
        """
        semantic_id = IDGenerator.generate_semantic_id(
            order_id, component_type, dimensions, refund_id
        )

        instance_id = IDGenerator.generate_instance_id(
            semantic_id, pricing_snapshot_id
        )

        return {
            'component_semantic_id': semantic_id,
            'component_instance_id': instance_id
        }


# Example usage for demonstration
if __name__ == "__main__":
    # Example 1: Order-level component
    ids1 = IDGenerator.generate_dual_ids(
        order_id="ORD-9001",
        component_type="Markup",
        dimensions={},
        pricing_snapshot_id="snap-001"
    )
    print("Order-level component:", ids1)

    # Example 2: Order detail level component
    ids2 = IDGenerator.generate_dual_ids(
        order_id="ORD-9001",
        component_type="BaseFare",
        dimensions={"order_detail_id": "001"},
        pricing_snapshot_id="snap-001"
    )
    print("Order detail component:", ids2)

    # Example 3: Passenger-segment level (flight)
    ids3 = IDGenerator.generate_dual_ids(
        order_id="ORD-9001",
        component_type="BaseFare",
        dimensions={
            "order_detail_id": "001",
            "pax_id": "A1",
            "leg_id": "CGK-SIN"
        },
        pricing_snapshot_id="snap-001"
    )
    print("Pax-segment component:", ids3)

    # Example 4: Same semantic ID, different snapshot (repricing)
    ids4 = IDGenerator.generate_dual_ids(
        order_id="ORD-9001",
        component_type="BaseFare",
        dimensions={
            "order_detail_id": "001",
            "pax_id": "A1",
            "leg_id": "CGK-SIN"
        },
        pricing_snapshot_id="snap-002"  # Different snapshot
    )
    print("Repriced component:", ids4)
    print(f"Semantic ID stable: {ids3['component_semantic_id'] == ids4['component_semantic_id']}")
    print(f"Instance ID different: {ids3['component_instance_id'] != ids4['component_instance_id']}")
