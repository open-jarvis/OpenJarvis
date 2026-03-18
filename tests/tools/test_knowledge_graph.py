"""Tests for knowledge graph storage backend (Phase 15.3)."""

from __future__ import annotations

from openjarvis.tools.storage.knowledge_graph import (
    Entity,
    KnowledgeGraphMemory,
    Relation,
)


class TestKnowledgeGraph:
    def _make_kg(self, tmp_path):
        return KnowledgeGraphMemory(db_path=tmp_path / "kg.db")

    def test_add_and_get_entity(self, tmp_path):
        kg = self._make_kg(tmp_path)
        entity = Entity(
            entity_id="e1",
            entity_type="concept",
            name="Machine Learning",
            properties={"field": "AI"},
        )
        kg.add_entity(entity)
        result = kg.get_entity("e1")
        assert result is not None
        assert result.name == "Machine Learning"
        assert result.properties["field"] == "AI"
        kg.close()

    def test_entity_not_found(self, tmp_path):
        kg = self._make_kg(tmp_path)
        assert kg.get_entity("nonexistent") is None
        kg.close()

    def test_add_relation(self, tmp_path):
        kg = self._make_kg(tmp_path)
        kg.add_entity(Entity(entity_id="a", entity_type="concept", name="A"))
        kg.add_entity(Entity(entity_id="b", entity_type="concept", name="B"))
        kg.add_relation(
            Relation(
                source_id="a",
                target_id="b",
                relation_type="depends_on",
            )
        )
        assert kg.relation_count() == 1
        kg.close()

    def test_neighbors(self, tmp_path):
        kg = self._make_kg(tmp_path)
        kg.add_entity(Entity(entity_id="a", entity_type="concept", name="A"))
        kg.add_entity(Entity(entity_id="b", entity_type="concept", name="B"))
        kg.add_entity(Entity(entity_id="c", entity_type="concept", name="C"))
        kg.add_relation(Relation(source_id="a", target_id="b", relation_type="uses"))
        kg.add_relation(Relation(source_id="a", target_id="c", relation_type="uses"))
        neighbors = kg.neighbors("a", direction="out")
        assert len(neighbors) == 2
        names = {n.name for n in neighbors}
        assert names == {"B", "C"}
        kg.close()

    def test_neighbors_with_type_filter(self, tmp_path):
        kg = self._make_kg(tmp_path)
        kg.add_entity(Entity(entity_id="a", entity_type="concept", name="A"))
        kg.add_entity(Entity(entity_id="b", entity_type="concept", name="B"))
        kg.add_entity(Entity(entity_id="c", entity_type="concept", name="C"))
        kg.add_relation(Relation(source_id="a", target_id="b", relation_type="uses"))
        kg.add_relation(
            Relation(
                source_id="a",
                target_id="c",
                relation_type="produces",
            )
        )
        neighbors = kg.neighbors("a", relation_type="uses", direction="out")
        assert len(neighbors) == 1
        assert neighbors[0].name == "B"
        kg.close()

    def test_query_pattern_entities(self, tmp_path):
        kg = self._make_kg(tmp_path)
        kg.add_entity(Entity(entity_id="t1", entity_type="tool", name="Calculator"))
        kg.add_entity(Entity(entity_id="t2", entity_type="tool", name="Search"))
        kg.add_entity(Entity(entity_id="a1", entity_type="agent", name="Bot"))
        result = kg.query_pattern(entity_type="tool")
        assert len(result.entities) == 2
        kg.close()

    def test_query_pattern_relations(self, tmp_path):
        kg = self._make_kg(tmp_path)
        kg.add_entity(Entity(entity_id="a", entity_type="x", name="A"))
        kg.add_entity(Entity(entity_id="b", entity_type="x", name="B"))
        kg.add_relation(Relation(source_id="a", target_id="b", relation_type="used"))
        result = kg.query_pattern(relation_type="used")
        assert len(result.relations) == 1
        kg.close()

    def test_memory_backend_store_retrieve(self, tmp_path):
        kg = self._make_kg(tmp_path)
        kg.store("doc1", "hello world", metadata={"name": "greeting"})
        content = kg.retrieve("doc1")
        assert content is not None
        assert "hello world" in content
        kg.close()

    def test_memory_backend_search(self, tmp_path):
        kg = self._make_kg(tmp_path)
        kg.store("doc1", "machine learning", metadata={"name": "ML"})
        kg.store("doc2", "deep learning", metadata={"name": "DL"})
        results = kg.search("learning")
        assert len(results) >= 1
        kg.close()

    def test_delete(self, tmp_path):
        kg = self._make_kg(tmp_path)
        kg.add_entity(Entity(entity_id="x", entity_type="test", name="X"))
        assert kg.delete("x")
        assert kg.get_entity("x") is None
        kg.close()

    def test_clear(self, tmp_path):
        kg = self._make_kg(tmp_path)
        kg.add_entity(Entity(entity_id="a", entity_type="test", name="A"))
        kg.add_entity(Entity(entity_id="b", entity_type="test", name="B"))
        kg.clear()
        assert kg.entity_count() == 0
        kg.close()

    def test_entity_count(self, tmp_path):
        kg = self._make_kg(tmp_path)
        assert kg.entity_count() == 0
        kg.add_entity(Entity(entity_id="a", entity_type="test", name="A"))
        assert kg.entity_count() == 1
        kg.close()
