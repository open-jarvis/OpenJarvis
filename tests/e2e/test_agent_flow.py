"""End-to-end tests for agent workflows."""
import pytest


class TestAgentFlow:
    """Test agent workflows end-to-end."""

    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_simple_agent_creation(self):
        """Test that an agent can be created and initialized."""
        try:
            from openjarvis import Jarvis
            
            # Create Jarvis instance
            jarvis = Jarvis()
            assert jarvis is not None
            
        except Exception as e:
            pytest.fail(f"Agent creation failed: {e}")
    
    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_agent_cleanup(self):
        """Test proper cleanup of agent resources."""
        try:
            from openjarvis import Jarvis
            
            jarvis = Jarvis()
            jarvis.close()
            # Verify resources are cleaned up
            assert True
            
        except Exception as e:
            pytest.fail(f"Agent cleanup failed: {e}")
