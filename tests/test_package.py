import hermes_nodes


def test_every_registered_node_has_a_display_name():
    assert set(hermes_nodes.NODE_CLASS_MAPPINGS) == set(hermes_nodes.NODE_DISPLAY_NAME_MAPPINGS)
    assert hermes_nodes.WEB_DIRECTORY == "./web"
