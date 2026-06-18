"""
tests/test_unit2_document.py
Unit 2：驗證 Block / TableData / Document 序列化與反序列化正確性。

執行：
    pytest tests/test_unit2_document.py -v
"""


from app.models.document import Block, BlockType, TableData, Document, OverviewLink


class TestBlockType:
    def test_all_contains_all_types(self):
        types = {BlockType.COVER, BlockType.OVERVIEW, BlockType.HEADING1,
                 BlockType.HEADING2, BlockType.BODY, BlockType.TABLE,
                 BlockType.IMAGE, BlockType.APPENDIX, BlockType.UNKNOWN}
        assert types == BlockType.ALL


class TestBlock:
    def test_default_id_generated(self):
        b = Block()
        assert b.id.startswith("blk-")

    def test_to_dict_roundtrip(self):
        b = Block(type=BlockType.BODY, page=2, content="測試內文", bbox=[0, 10, 200, 50])
        d = b.to_dict()
        b2 = Block.from_dict(d)
        assert b2.type    == b.type
        assert b2.page    == b.page
        assert b2.content == b.content
        assert b2.bbox    == b.bbox

    def test_block_with_table_data(self):
        td = TableData(
            headers=["品名", "單價", "數量", "小計"],
            rows=[["鋼板 A", "1200", "10", "12000"]],
            total=12000.0,
            linked_overview_cell="B3",
        )
        b = Block(type=BlockType.TABLE, table_data=td)
        d = b.to_dict()
        b2 = Block.from_dict(d)
        assert b2.table_data is not None
        assert b2.table_data.total == 12000.0
        assert b2.table_data.linked_overview_cell == "B3"
        assert b2.table_data.headers[0] == "品名"


class TestTableData:
    def test_roundtrip(self):
        td = TableData(headers=["A", "B"], rows=[["1", "2"]], total=3.0)
        td2 = TableData.from_dict(td.to_dict())
        assert td2.headers == ["A", "B"]
        assert td2.total == 3.0


class TestDocument:
    def _make_doc(self) -> Document:
        doc = Document(doc_id="abc123", filename="test.pdf", page_count=3)
        doc.blocks = [
            Block(type=BlockType.COVER,  page=1, content="封面"),
            Block(type=BlockType.HEADING1, page=2, content="第一章"),
            Block(type=BlockType.BODY,   page=2, content="內文段落"),
        ]
        doc.overview_links = [
            OverviewLink(source_block_id="blk-001",
                         overview_block_id="blk-002",
                         cell="B3")
        ]
        return doc

    def test_to_dict_roundtrip(self):
        doc = self._make_doc()
        d   = doc.to_dict()
        doc2 = Document.from_dict(d)
        assert doc2.doc_id     == "abc123"
        assert doc2.page_count == 3
        assert len(doc2.blocks) == 3
        assert doc2.blocks[0].content == "封面"

    def test_get_block(self):
        doc = self._make_doc()
        blk = doc.get_block(doc.blocks[1].id)
        assert blk is not None
        assert blk.type == BlockType.HEADING1

    def test_get_block_not_found(self):
        doc = self._make_doc()
        assert doc.get_block("nonexistent") is None

    def test_blocks_by_type(self):
        doc = self._make_doc()
        headings = doc.blocks_by_type(BlockType.HEADING1)
        assert len(headings) == 1

    def test_blocks_on_page(self):
        doc = self._make_doc()
        page2 = doc.blocks_on_page(2)
        assert len(page2) == 2

    def test_overview_links_roundtrip(self):
        doc = self._make_doc()
        d   = doc.to_dict()
        doc2 = Document.from_dict(d)
        assert len(doc2.overview_links) == 1
        assert doc2.overview_links[0].cell == "B3"
