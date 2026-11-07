"""Unit tests for DSM _ExpInfo.xml parsing."""

from pathlib import Path

from dsm2emp.parser.expinfo import parse_expinfo_xml


def test_parse_expinfo_xml_basic(tmp_path: Path) -> None:
    """Test extracting Name, Description, and LDAP Manufacturer."""
    xml_content = """<?xml version="1.0" encoding="UTF-8"?>
<DsmExport Version="7.5.1.0">
    <ArrayOfMdsObject>
        <MdsObject>
            <SchemaTag>eScriptPackage</SchemaTag>
            <Name>7Zip_25.01</Name>
            <Description>Test Description for 7Zip</Description>
            <ObjectLocation>&lt;LDAP://o=7Zip_25.01,DC=7Zip,DC=Freeware&gt;</ObjectLocation>
            <PropGroupList>
                <MdsPropGroup>
                    <PropertyList>
                        <MdsProperty>
                            <Value>1</Value>
                            <Tag>IsLastRevision</Tag>
                        </MdsProperty>
                        <MdsProperty>
                            <Value>13</Value>
                            <Tag>SoftwareRevision</Tag>
                        </MdsProperty>
                        <MdsProperty>
                            <Value>Freigegeben durch IT.</Value>
                            <Tag>SwRevisionComment</Tag>
                        </MdsProperty>
                        <MdsProperty>
                            <Value>2025-11-04T13:21:17Z</Value>
                            <Tag>ReleaseDate</Tag>
                        </MdsProperty>
                    </PropertyList>
                </MdsPropGroup>
            </PropGroupList>
        </MdsObject>
    </ArrayOfMdsObject>
</DsmExport>
"""
    xml_file = tmp_path / "_ExpInfo.xml"
    xml_file.write_text(xml_content, encoding="utf-8")

    meta = parse_expinfo_xml(xml_file)
    assert meta.name == "7Zip_25.01"
    assert meta.manufacturer == "7Zip"
    assert meta.description == "Test Description for 7Zip"
    assert meta.version == "25.01"
    assert meta.revision == "13"
    assert meta.revision_comment == "Freigegeben durch IT."
    assert meta.release_date == "2025-11-04T13:21:17Z"


def test_parse_expinfo_xml_empty_or_missing(tmp_path: Path) -> None:
    """Test non-existent file returns default empty ExpInfoMetadata."""
    missing = tmp_path / "nonexistent.xml"
    meta = parse_expinfo_xml(missing)
    assert meta.name is None
    assert meta.manufacturer is None
