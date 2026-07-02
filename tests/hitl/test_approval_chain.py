# tests/hitl/test_approval_chain.py

"""
Tests for tools.hitl.approval_chain — ApprovalLevel, ApprovalChain, RoleRegistry, build_chain_from_registry.
"""

from datetime import timedelta

import pytest

from tools.hitl.approval_chain import (
    ApprovalChain,
    ApprovalLevel,
    RoleRegistry,
    build_chain_from_registry,
)


# ── ApprovalLevel ───────────────────────────────────────────────

class TestApprovalLevel:

    def test_basic_creation(self):
        level = ApprovalLevel(
            level=1,
            role_required="tech_lead",
            approvers=("alice", "bob"),
            sla=timedelta(hours=24),
        )
        assert level.level == 1
        assert level.role_required == "tech_lead"
        assert level.approvers == ("alice", "bob")
        assert level.sla == timedelta(hours=24)
        assert level.escalation_target is None

    def test_with_escalation_target(self):
        level = ApprovalLevel(
            level=1,
            role_required="tech_lead",
            approvers=("alice",),
            sla=timedelta(hours=12),
            escalation_target=2,
        )
        assert level.escalation_target == 2

    def test_level_must_be_positive(self):
        with pytest.raises(ValueError, match="level must be >= 1"):
            ApprovalLevel(
                level=0,
                role_required="tech_lead",
                approvers=("alice",),
                sla=timedelta(hours=1),
            )

    def test_approvers_cannot_be_empty(self):
        with pytest.raises(ValueError, match="approvers cannot be empty"):
            ApprovalLevel(
                level=1,
                role_required="tech_lead",
                approvers=(),
                sla=timedelta(hours=1),
            )

    def test_sla_must_be_positive(self):
        with pytest.raises(ValueError, match="sla must be positive"):
            ApprovalLevel(
                level=1,
                role_required="tech_lead",
                approvers=("alice",),
                sla=timedelta(seconds=0),
            )

    def test_negative_sla_rejected(self):
        with pytest.raises(ValueError, match="sla must be positive"):
            ApprovalLevel(
                level=1,
                role_required="tech_lead",
                approvers=("alice",),
                sla=timedelta(seconds=-1),
            )

    def test_primary_approver(self):
        level = ApprovalLevel(
            level=1,
            role_required="tech_lead",
            approvers=("alice", "bob", "charlie"),
            sla=timedelta(hours=24),
        )
        assert level.primary_approver == "alice"

    def test_frozen(self):
        level = ApprovalLevel(
            level=1,
            role_required="tech_lead",
            approvers=("alice",),
            sla=timedelta(hours=24),
        )
        with pytest.raises(AttributeError):
            level.level = 2


# ── ApprovalChain ───────────────────────────────────────────────

class TestApprovalChain:

    def _make_chain(self) -> ApprovalChain:
        return ApprovalChain([
            ApprovalLevel(1, "tech_lead", ("alice",), timedelta(hours=24), escalation_target=2),
            ApprovalLevel(2, "manager", ("bob",), timedelta(hours=48)),
        ])

    def test_add_level(self):
        chain = ApprovalChain()
        chain.add_level(ApprovalLevel(1, "tech_lead", ("alice",), timedelta(hours=24)))
        assert len(chain) == 1

    def test_add_level_sorts_by_level(self):
        chain = ApprovalChain()
        chain.add_level(ApprovalLevel(2, "manager", ("bob",), timedelta(hours=24)))
        chain.add_level(ApprovalLevel(1, "tech_lead", ("alice",), timedelta(hours=24)))
        assert chain.levels[0].level == 1
        assert chain.levels[1].level == 2

    def test_duplicate_level_raises(self):
        chain = ApprovalChain()
        chain.add_level(ApprovalLevel(1, "tech_lead", ("alice",), timedelta(hours=24)))
        with pytest.raises(ValueError, match="Duplicate level 1"):
            chain.add_level(ApprovalLevel(1, "other", ("bob",), timedelta(hours=24)))

    def test_get_level(self):
        chain = self._make_chain()
        level = chain.get_level(1)
        assert level is not None
        assert level.role_required == "tech_lead"

    def test_get_level_missing(self):
        chain = self._make_chain()
        assert chain.get_level(99) is None

    def test_get_escalation_target(self):
        chain = self._make_chain()
        target = chain.get_escalation_target(1)
        assert target is not None
        assert target.level == 2
        assert target.role_required == "manager"

    def test_get_escalation_target_none(self):
        chain = self._make_chain()
        assert chain.get_escalation_target(2) is None  # level 2 has no escalation_target

    def test_get_escalation_target_missing_level(self):
        chain = self._make_chain()
        assert chain.get_escalation_target(99) is None

    def test_max_level(self):
        chain = self._make_chain()
        assert chain.max_level == 2

    def test_max_level_empty(self):
        chain = ApprovalChain()
        assert chain.max_level == 0

    def test_is_empty(self):
        chain = ApprovalChain()
        assert chain.is_empty
        chain.add_level(ApprovalLevel(1, "tech_lead", ("alice",), timedelta(hours=24)))
        assert not chain.is_empty

    def test_iteration(self):
        chain = self._make_chain()
        levels = list(chain)
        assert len(levels) == 2
        assert levels[0].level == 1
        assert levels[1].level == 2

    def test_len(self):
        chain = self._make_chain()
        assert len(chain) == 2


# ── RoleRegistry ────────────────────────────────────────────────

class TestRoleRegistry:

    def test_assign_and_get(self):
        reg = RoleRegistry()
        reg.assign("tech_lead", "alice")
        assert reg.get_approvers("tech_lead") == ["alice"]

    def test_assign_multiple_approvers(self):
        reg = RoleRegistry()
        reg.assign("tech_lead", "alice")
        reg.assign("tech_lead", "charlie")
        approvers = reg.get_approvers("tech_lead")
        assert "alice" in approvers
        assert "charlie" in approvers
        assert len(approvers) == 2

    def test_assign_same_approver_twice_no_duplicates(self):
        reg = RoleRegistry()
        reg.assign("tech_lead", "alice")
        reg.assign("tech_lead", "alice")
        assert reg.get_approvers("tech_lead") == ["alice"]

    def test_assign_multiple_roles(self):
        reg = RoleRegistry()
        reg.assign("tech_lead", "alice")
        reg.assign("manager", "alice")
        reg.assign("manager", "bob")
        assert reg.has_role("alice", "tech_lead")
        assert reg.has_role("alice", "manager")
        assert not reg.has_role("bob", "tech_lead")

    def test_remove_approver(self):
        reg = RoleRegistry()
        reg.assign("tech_lead", "alice")
        assert reg.remove("tech_lead", "alice") is True
        assert reg.get_approvers("tech_lead") == []

    def test_remove_approver_cleans_up_empty_role(self):
        reg = RoleRegistry()
        reg.assign("tech_lead", "alice")
        reg.remove("tech_lead", "alice")
        assert "tech_lead" not in reg._roles

    def test_remove_nonexistent_role(self):
        reg = RoleRegistry()
        assert reg.remove("nonexistent", "alice") is False

    def test_remove_nonexistent_approver(self):
        reg = RoleRegistry()
        reg.assign("tech_lead", "alice")
        assert reg.remove("tech_lead", "bob") is False

    def test_has_role(self):
        reg = RoleRegistry()
        reg.assign("tech_lead", "alice")
        assert reg.has_role("alice", "tech_lead")
        assert not reg.has_role("bob", "tech_lead")

    def test_roles_for(self):
        reg = RoleRegistry()
        reg.assign("tech_lead", "alice")
        reg.assign("manager", "alice")
        reg.assign("manager", "bob")
        roles = reg.roles_for("alice")
        assert "tech_lead" in roles
        assert "manager" in roles
        assert len(roles) == 2

    def test_roles_property(self):
        reg = RoleRegistry()
        reg.assign("tech_lead", "alice")
        reg.assign("manager", "bob")
        roles = reg.roles
        assert "tech_lead" in roles
        assert "manager" in roles

    def test_len(self):
        reg = RoleRegistry()
        assert len(reg) == 0
        reg.assign("tech_lead", "alice")
        assert len(reg) == 1
        reg.assign("manager", "bob")
        assert len(reg) == 2

    def test_contains(self):
        reg = RoleRegistry()
        reg.assign("tech_lead", "alice")
        assert "tech_lead" in reg
        assert "manager" not in reg


# ── build_chain_from_registry ──────────────────────────────────

class TestBuildChainFromRegistry:

    def _make_registry(self) -> RoleRegistry:
        reg = RoleRegistry()
        reg.assign("tech_lead", "alice")
        reg.assign("manager", "bob")
        reg.assign("director", "carol")
        return reg

    def test_low_risk_chain(self):
        reg = self._make_registry()
        chain = build_chain_from_registry(reg, "low")
        assert len(chain) == 1
        assert chain.get_level(1).role_required == "tech_lead"
        assert chain.get_level(1).approvers == ("alice",)

    def test_medium_risk_chain(self):
        reg = self._make_registry()
        chain = build_chain_from_registry(reg, "medium")
        assert len(chain) == 2
        assert chain.get_level(1).role_required == "tech_lead"
        assert chain.get_level(2).role_required == "manager"
        assert chain.get_level(1).escalation_target == 2

    def test_high_risk_chain(self):
        reg = self._make_registry()
        chain = build_chain_from_registry(reg, "high")
        assert len(chain) == 3
        assert chain.get_level(1).role_required == "tech_lead"
        assert chain.get_level(2).role_required == "manager"
        assert chain.get_level(3).role_required == "director"
        assert chain.get_level(1).escalation_target == 2
        assert chain.get_level(2).escalation_target == 3
        assert chain.get_level(3).escalation_target is None

    def test_missing_role_skips_level(self):
        """如果某个角色没有审批人，该层级被跳过。"""
        reg = RoleRegistry()
        reg.assign("tech_lead", "alice")
        # manager 和 director 没有审批人
        chain = build_chain_from_registry(reg, "high")
        assert len(chain) == 1
        assert chain.get_level(1).role_required == "tech_lead"

    def test_unknown_risk_defaults_to_low(self):
        reg = self._make_registry()
        chain = build_chain_from_registry(reg, "unknown_risk")
        assert len(chain) == 1

    def test_sla_values(self):
        reg = self._make_registry()
        chain = build_chain_from_registry(reg, "high")
        assert chain.get_level(1).sla == timedelta(hours=6)
        assert chain.get_level(2).sla == timedelta(hours=12)
        assert chain.get_level(3).sla == timedelta(hours=24)
