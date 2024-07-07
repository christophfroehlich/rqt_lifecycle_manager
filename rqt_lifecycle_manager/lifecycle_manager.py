# Copyright 2024 AIT - Austrian Institute of Technology GmbH
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
import sys

from ament_index_python.packages import get_package_share_directory
from python_qt_binding import loadUi
from python_qt_binding.QtCore import QAbstractTableModel, Qt, QTimer
from python_qt_binding.QtGui import QFont, QIcon
from python_qt_binding.QtWidgets import QHeaderView, QMenu, QWidget
from qt_gui.plugin import Plugin
from lifecycle_msgs.msg import Transition

from ros2lifecycle.api import get_node_names
from ros2lifecycle.api import call_get_states
from ros2lifecycle.api import call_change_states

from collections import namedtuple

# Define a simple structure with fields 'name' and 'state'
NodeState = namedtuple("NodeState", ["name", "state"])


class LifecycleManager(Plugin):
    """Graphical frontend for interacting with lifecycle nodes."""

    _update_freq = 1  # Hz

    def __init__(self, context):
        super().__init__(context)
        self.setObjectName("LifecycleManager")

        # Create QWidget and extend it with all the attributes and children
        # from the UI file
        self._widget = QWidget()
        ui_file = os.path.join(
            get_package_share_directory("rqt_lifecycle_manager"),
            "resource",
            "lifecycle_manager.ui",
        )
        loadUi(ui_file, self._widget)
        self._widget.setObjectName("LifecycleManagerUi")

        # Show _widget.windowTitle on left-top of each plugin (when
        # it's set in _widget). This is useful when you open multiple
        # plugins at once. Also if you open multiple instances of your
        # plugin at once, these lines add number to make it easy to
        # tell from pane to pane.
        if context.serial_number() > 1:
            self._widget.setWindowTitle(f"{self._widget.windowTitle()} {context.serial_number()}")
        # Add widget to the user interface
        context.add_widget(self._widget)

        # Initialize members
        self._lc_node_names = []  # list of lifecycle node names
        self._lc_nodes = []  # list of lifecycle node status
        self._table_model = None

        # Store reference to node
        self._node = context.node

        # lc node state icons
        path = get_package_share_directory("rqt_lifecycle_manager")
        self._icons = {
            "active": QIcon(f"{path}/resource/led_green.png"),
            "finalized": QIcon(f"{path}/resource/led_off.png"),
            "inactive": QIcon(f"{path}/resource/led_red.png"),
            "unconfigured": QIcon(f"{path}/resource/led_off.png"),
        }

        # lc nodes display
        table_view = self._widget.table_view
        table_view.setContextMenuPolicy(Qt.CustomContextMenu)
        table_view.customContextMenuRequested.connect(self._on_lc_node_menu)

        header = table_view.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setContextMenuPolicy(Qt.CustomContextMenu)

        # Timer for listing nodes
        self._update_node_list_timer = QTimer(self)
        self._update_node_list_timer.setInterval(int(1000.0 / self._update_freq))
        self._update_node_list_timer.timeout.connect(self._update_node_list)
        self._update_node_list_timer.start()

        # Timer for running lc node updates
        self._update_nodes_state_timer = QTimer(self)
        self._update_nodes_state_timer.setInterval(int(1000.0 / self._update_freq))
        self._update_nodes_state_timer.timeout.connect(self._update_nodes_state)
        self._update_nodes_state_timer.start()

    def shutdown_plugin(self):
        self._update_node_list_timer.stop()
        self._update_nodes_state_timer.stop()

    def save_settings(self, plugin_settings, instance_settings):
        pass

    def restore_settings(self, plugin_settings, instance_settings):
        pass

    def _update_node_list(self):
        node_names = self._list_lc_nodes()

        # Update lc node display, if necessary
        if self._lc_node_names != node_names:
            self._lc_node_names = node_names
            self._update_nodes_state()

    def _update_nodes_state(self):
        # Update lc node state
        self._lc_nodes = []
        for lc_node in self._lc_node_names:
            states = call_get_states(node=self._node, node_names=[lc_node.name])
            # output exceptions
            for node_name in sorted(states.keys()):
                state = states[node_name]
                if isinstance(state, Exception):
                    print(
                        "Exception while calling service of node " f"'{node_name}': {state}",
                        file=sys.stderr,
                    )
                    del states[node_name]

            # output current states
            for node_name in sorted(states.keys()):
                state = states[node_name]
                self._lc_nodes.append(NodeState(name=node_name, state=state.label))

        self._show_lc_nodes()

    def _list_lc_nodes(self):
        """
        List the lifecycle nodes.

        @rtype [str]
        """
        try:
            node_names = get_node_names(node=self._node, include_hidden_nodes=False)
            return node_names
        except RuntimeError as e:
            print(e)
            return []

    def _show_lc_nodes(self):
        table_view = self._widget.table_view
        self._table_model = LifecycleNodeTable(self._lc_nodes, self._icons)
        table_view.setModel(self._table_model)

    def _on_lc_node_menu(self, pos):
        # Get data of selected node
        row = self._widget.table_view.rowAt(pos.y())
        if row < 0:
            return  # Cursor is not under a valid item

        lc_node = self._lc_nodes[row]

        # Show context menu
        menu = QMenu(self._widget.table_view)
        if lc_node.state == "active":
            action_deactivate = menu.addAction(self._icons["inactive"], "Deactivate")
            action_unspawn = menu.addAction(self._icons["unconfigured"], "Deactivate and cleanup")
            action_shutdown = menu.addAction(self._icons["finalized"], "Shutdown")
        elif lc_node.state == "inactive":
            action_activate = menu.addAction(self._icons["active"], "Activate")
            action_cleanup = menu.addAction(self._icons["unconfigured"], "Cleanup")
            action_shutdown = menu.addAction(self._icons["finalized"], "Shutdown")
        elif lc_node.state == "unconfigured":
            action_configure = menu.addAction(self._icons["inactive"], "Configure")
            action_spawn = menu.addAction(self._icons["active"], "Configure and Activate")
            action_shutdown = menu.addAction(self._icons["finalized"], "Shutdown")
        else:
            pass  # finalized

        action = menu.exec_(self._widget.table_view.mapToGlobal(pos))

        # Evaluate user action
        if lc_node.state == "active":
            if action is action_deactivate:
                self._call_transition(lc_node.name, "deactivate")
            elif action is action_shutdown:
                self._call_transition(lc_node.name, "shutdown")
            elif action is action_unspawn:
                self._call_transition(lc_node.name, "deactivate")
                self._call_transition(lc_node.name, "cleanup")
        elif lc_node.state == "inactive":
            if action is action_activate:
                self._call_transition(lc_node.name, "activate")
            elif action is action_cleanup:
                self._call_transition(lc_node.name, "cleanup")
            elif action is action_shutdown:
                self._call_transition(lc_node.name, "shutdown")
        elif lc_node.state == "unconfigured":
            if action is action_configure:
                self._call_transition(lc_node.name, "configure")
            elif action is action_shutdown:
                self._call_transition(lc_node.name, "shutdown")
            elif action is action_spawn:
                self._call_transition(lc_node.name, "configure")
                self._call_transition(lc_node.name, "activate")
        else:
            pass  # finalized

    def _call_transition(self, node_name, transition_label):

        transition = Transition(label=transition_label)  #

        results = call_change_states(node=self._node, transitions={node_name: transition})
        result = results[node_name]

        # output response
        if isinstance(result, Exception):
            print(
                "Exception while calling service of node " f"'{node_name}': {result}",
                file=sys.stderr,
            )
        elif result:
            print("Transitioning successful")
        else:
            print("Transitioning failed", file=sys.stderr)


class LifecycleNodeTable(QAbstractTableModel):
    """
    Model containing lifecycle node information for tabular display.

    The model allows display of basic read-only information
    """

    def __init__(self, node_info, icons, parent=None):
        QAbstractTableModel.__init__(self, parent)
        self._data = node_info
        self._icons = icons

    def rowCount(self, parent):
        return len(self._data)

    def columnCount(self, parent):
        return 2

    def headerData(self, col, orientation, role):
        if orientation != Qt.Horizontal or role != Qt.DisplayRole:
            return None
        if col == 0:
            return "node"
        elif col == 1:
            return "state"

    def data(self, index, role):
        if not index.isValid():
            return None

        lc_node = self._data[index.row()]

        if role == Qt.DisplayRole:
            if index.column() == 0:
                return lc_node.name
            elif index.column() == 1:
                return lc_node.state or "not loaded"

        if role == Qt.DecorationRole and index.column() == 0:
            return self._icons.get(lc_node.state)

        if role == Qt.FontRole and index.column() == 0:
            bf = QFont()
            bf.setBold(True)
            return bf

        if role == Qt.TextAlignmentRole and index.column() == 1:
            return Qt.AlignCenter
