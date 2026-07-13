"""Blueprint Tracker tab (#157; split into its own tab in 2.2.x, #222).

A search-filtered shuttle of every item that appears in a mission's
POTENTIAL BLUEPRINTS reward on the left, the items the user owns on the
right, and arrow buttons to move multi-selected items between them. Owned
items get an ``[Owned]`` tag wherever they show up in a mission's potential
blueprint rewards. Originally a section at the bottom of the Enhancements
tab; moved to its own tab (still hosting most of its i18n strings under the
``enhancements.blueprints_*`` namespace — unchanged on purpose, since only
the tab housing it changed, not the strings' meaning).

The available universe is fed in by MainWindow via ``set_blueprint_items``
(it is computed from the loaded mission strings, which this tab can't see).
"""
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView, QCheckBox, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QPushButton, QScrollArea, QSizePolicy,
    QVBoxLayout, QWidget,
)

from src.gui.enhancements_tab import _NoScrollComboBox
from src.utils.i18n import tr
from src.utils.settings import AppSettings


class _NoWheelComboBox(_NoScrollComboBox):
    """A combo box that never responds to mouse wheel scroll, focused or not.

    _NoScrollComboBox (#197) only ignores the wheel while unfocused, so a
    focused wheel scroll still changes its value — intentional there, but
    wrong for a pure filter dropdown: click Mission/Type/Class/Size/Grade
    once to pick a value, it keeps focus, and later scrolling the page while
    the mouse happens to be over it silently changes the filter instead of
    scrolling (#224). Always ignoring the wheel avoids that trap; still
    inherits _NoScrollComboBox's popup-placement fix.
    """

    def wheelEvent(self, event):  # noqa: N802 (Qt override)
        event.ignore()


class BlueprintTrackerTab(QWidget):
    """Track owned blueprints against mission POTENTIAL BLUEPRINTS rewards."""

    # The owned-blueprint set changed. MainWindow re-weaves [Owned] tags into
    # the strings table and refreshes it.
    owned_items_changed = pyqtSignal()
    # The user clicked "Scan Logs for Owned Blueprints". MainWindow owns the
    # worker/progress-dialog lifecycle (the threading model every other
    # file-scan action in this app follows) and calls back into
    # AppSettings.set_owned_items() + _recompute_owned() on completion,
    # which re-renders this tab the same way any other Owned change does.
    scan_logs_requested = pyqtSignal()
    # The user clicked "Apply Owned Tags". MainWindow re-weaves the [Owned]
    # tag into the loaded strings' blueprint-list bullets so the current
    # Owned set is reflected on demand, without needing to move an item
    # between the two lists first.
    apply_owned_requested = pyqtSignal()

    def __init__(self):
        super().__init__()
        # name -> BlueprintItem (or None for a bare name), set by MainWindow.
        # Owned state itself lives in AppSettings (single source of truth).
        self._blueprint_meta: dict = {}
        # Gates the Apply Owned Tags button, same pattern as the
        # Enhancements tab's Generate Enhancements / Save Tag Changes:
        # disabled until the Owned set changes since the last apply.
        self._owned_dirty = False
        self.setup_ui()

    def setup_ui(self):
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        self._title_label = QLabel(tr("blueprint_tracker.title"))
        self._title_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(self._title_label)

        self._blueprints_desc_label = QLabel(tr("enhancements.blueprints_desc"))
        self._blueprints_desc_label.setProperty("role", "secondary")
        self._blueprints_desc_label.setStyleSheet("font-size: 11px;")
        self._blueprints_desc_label.setWordWrap(True)
        layout.addWidget(self._blueprints_desc_label)

        # Always visible regardless of the empty-state gate below — scanning
        # logs doesn't need mission data loaded, it reads the player's own
        # earned-blueprint history straight from Star Citizen's log files.
        top_btn_row = QHBoxLayout()
        self._scan_logs_btn = QPushButton(tr("blueprint_tracker.scan_logs_btn"))
        self._scan_logs_btn.setToolTip(tr("blueprint_tracker.scan_logs_tooltip"))
        self._scan_logs_btn.clicked.connect(self.scan_logs_requested.emit)
        self._scan_logs_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        top_btn_row.addWidget(self._scan_logs_btn, 1)

        self._apply_owned_btn = QPushButton(tr("blueprint_tracker.apply_owned_tag_btn"))
        self._apply_owned_btn.clicked.connect(self._on_apply_owned_clicked)
        self._apply_owned_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        top_btn_row.addWidget(self._apply_owned_btn, 1)
        self._set_owned_btn_dirty(False)

        layout.addLayout(top_btn_row)

        # Shown instead of the lists when no blueprint items exist yet (mission
        # enhancements not generated) — the same precondition the stars had.
        self._blueprints_empty_note = QLabel(tr("enhancements.blueprints_empty_note"))
        self._blueprints_empty_note.setProperty("role", "secondary")
        self._blueprints_empty_note.setStyleSheet("font-size: 11px; font-style: italic;")
        self._blueprints_empty_note.setWordWrap(True)
        layout.addWidget(self._blueprints_empty_note)

        self._blueprints_search = QLineEdit()
        self._blueprints_search.setPlaceholderText(
            tr("enhancements.blueprints_search_placeholder")
        )
        self._blueprints_search.setClearButtonEnabled(True)
        self._blueprints_search.textChanged.connect(self._refilter_blueprints_available)
        layout.addWidget(self._blueprints_search)

        # Display-only toggle (#221): show each item's Tag Builder tag inline
        # instead of the bare name. Matching/filtering/Owned tracking always
        # use the bare name regardless — see BlueprintItem.tagged_name.
        self._blueprints_show_tags = QCheckBox(
            tr("enhancements.blueprints_show_tags_checkbox")
        )
        self._blueprints_show_tags.setChecked(AppSettings.get_blueprint_show_tags())
        self._blueprints_show_tags.toggled.connect(self._on_blueprints_show_tags_toggled)
        layout.addWidget(self._blueprints_show_tags)

        mission_row = QHBoxLayout()
        self._blueprints_mission_label = QLabel(tr("enhancements.blueprints_mission_label"))
        self._blueprints_mission_label.setProperty("role", "secondary")
        mission_row.addWidget(self._blueprints_mission_label)
        self._blueprints_mission_combo = _NoWheelComboBox()
        self._blueprints_mission_combo.addItem(tr("enhancements.blueprints_facet_any"), None)
        self._blueprints_mission_combo.currentIndexChanged.connect(
            self._refilter_blueprints_available
        )
        mission_row.addWidget(self._blueprints_mission_combo, 1)
        layout.addLayout(mission_row)

        # Component-attribute facets. Each combo's first row is "Any" (data
        # None); the rest are enumerated from the loaded metadata. Attributes
        # exist only for ship components, so the coverage note sets expectations.
        facet_row = QHBoxLayout()
        self._blueprints_facet_combos = {}
        self._blueprints_facet_labels = {}
        for attr, label_key in (
            ("type", "enhancements.blueprints_facet_type"),
            ("cls", "enhancements.blueprints_facet_class"),
            ("size", "enhancements.blueprints_facet_size"),
            ("grade", "enhancements.blueprints_facet_grade"),
        ):
            lbl = QLabel(tr(label_key))
            lbl.setProperty("role", "secondary")
            combo = _NoWheelComboBox()
            combo.addItem(tr("enhancements.blueprints_facet_any"), None)
            combo.currentIndexChanged.connect(self._refilter_blueprints_available)
            self._blueprints_facet_combos[attr] = combo
            self._blueprints_facet_labels[label_key] = lbl
            facet_row.addWidget(lbl)
            facet_row.addWidget(combo, 1)
        layout.addLayout(facet_row)

        self._blueprints_filter_note = QLabel(tr("enhancements.blueprints_filter_note"))
        self._blueprints_filter_note.setProperty("role", "secondary")
        self._blueprints_filter_note.setStyleSheet("font-size: 10px;")
        self._blueprints_filter_note.setWordWrap(True)
        layout.addWidget(self._blueprints_filter_note)

        lists_row = QHBoxLayout()

        avail_col = QVBoxLayout()
        self._blueprints_available_label = QLabel(
            tr("enhancements.blueprints_available_label")
        )
        avail_col.addWidget(self._blueprints_available_label)
        self._blueprints_available_list = QListWidget()
        self._blueprints_available_list.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self._blueprints_available_list.itemDoubleClicked.connect(
            lambda _it: self._own_selected_blueprints()
        )
        avail_col.addWidget(self._blueprints_available_list)
        lists_row.addLayout(avail_col, 1)

        arrows = QVBoxLayout()
        arrows.addStretch()
        self._blueprints_add_btn = QPushButton("→")  # →
        self._blueprints_add_btn.setToolTip(tr("enhancements.blueprints_add_tooltip"))
        self._blueprints_add_btn.clicked.connect(self._own_selected_blueprints)
        arrows.addWidget(self._blueprints_add_btn)
        self._blueprints_remove_btn = QPushButton("←")  # ←
        self._blueprints_remove_btn.setToolTip(tr("enhancements.blueprints_remove_tooltip"))
        self._blueprints_remove_btn.clicked.connect(self._unown_selected_blueprints)
        arrows.addWidget(self._blueprints_remove_btn)
        arrows.addStretch()
        lists_row.addLayout(arrows)

        owned_col = QVBoxLayout()
        self._blueprints_owned_label = QLabel(
            tr("enhancements.blueprints_owned_label")
        )
        owned_col.addWidget(self._blueprints_owned_label)
        self._blueprints_owned_list = QListWidget()
        self._blueprints_owned_list.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self._blueprints_owned_list.itemDoubleClicked.connect(
            lambda _it: self._unown_selected_blueprints()
        )
        owned_col.addWidget(self._blueprints_owned_list)
        lists_row.addLayout(owned_col, 1)

        layout.addLayout(lists_row, 1)
        layout.addStretch()

        self._render_blueprint_lists()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.viewport().setAutoFillBackground(False)
        content.setAutoFillBackground(False)
        scroll.setWidget(content)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    def retranslate_ui(self) -> None:
        """Re-apply tr() to every text-bearing widget after a language switch."""
        self._title_label.setText(tr("blueprint_tracker.title"))
        self._blueprints_desc_label.setText(tr("enhancements.blueprints_desc"))
        self._scan_logs_btn.setText(tr("blueprint_tracker.scan_logs_btn"))
        self._scan_logs_btn.setToolTip(tr("blueprint_tracker.scan_logs_tooltip"))
        self._apply_owned_btn.setText(tr("blueprint_tracker.apply_owned_tag_btn"))
        self._set_owned_btn_dirty(self._owned_dirty)  # re-applies the right tooltip
        self._blueprints_empty_note.setText(tr("enhancements.blueprints_empty_note"))
        self._blueprints_search.setPlaceholderText(tr("enhancements.blueprints_search_placeholder"))
        self._blueprints_show_tags.setText(tr("enhancements.blueprints_show_tags_checkbox"))
        self._blueprints_mission_label.setText(tr("enhancements.blueprints_mission_label"))
        self._blueprints_filter_note.setText(tr("enhancements.blueprints_filter_note"))
        self._blueprints_available_label.setText(tr("enhancements.blueprints_available_label"))
        self._blueprints_owned_label.setText(tr("enhancements.blueprints_owned_label"))
        self._blueprints_add_btn.setToolTip(tr("enhancements.blueprints_add_tooltip"))
        self._blueprints_remove_btn.setToolTip(tr("enhancements.blueprints_remove_tooltip"))
        for label_key, lbl in self._blueprints_facet_labels.items():
            lbl.setText(tr(label_key))

    @staticmethod
    def _available_blueprints(all_names, owned) -> list:
        """Blueprint items not yet owned, sorted case-insensitively.

        Pure (Qt-free) so the available/owned split is unit-testable. Accepts a
        name iterable or a ``{name: meta}`` mapping (dict keys are the names).
        """
        return sorted(set(all_names) - set(owned), key=str.lower)

    def set_blueprint_items(self, meta) -> None:
        """Receive the blueprint-item metadata from MainWindow.

        *meta* is ``{name: BlueprintItem}`` (a bare name set/list is tolerated
        too — items then carry no filter attributes). Called after every load
        and every owned-set change, so the lists track the loaded strings.
        """
        if isinstance(meta, dict):
            self._blueprint_meta = dict(meta)
        else:
            self._blueprint_meta = {n: None for n in (meta or ())}
        self._populate_filter_combos()
        self._render_blueprint_lists()

    def _facet_value(self, name: str, attr: str):
        """The value of one facet attribute for *name*, or None if unknown."""
        item = self._blueprint_meta.get(name)
        return getattr(item, attr, None) if item is not None else None

    @staticmethod
    def _facet_sort_key(attr: str, value: str):
        """Sort facet values naturally, keeping "Other" pinned last.

        The size facet holds bare numbers ("0", "1", ..., "10") and needs a
        numeric sort — a plain string sort would put "10" before "2". "Other"
        only ever appears as a Type value, so the other facets are unaffected.
        """
        if attr == "size":
            try:
                return (False, int(value))
            except (TypeError, ValueError):
                return (False, value)
        return (value == "Other", value)

    def _populate_filter_combos(self) -> None:
        """Refill the mission and facet combos with the values present in the
        metadata, preserving each current selection where it still exists."""
        # Mission combo: the union of every item's mission names.
        missions = sorted({
            m for item in self._blueprint_meta.values()
            for m in getattr(item, "missions", ()) or ()
        }, key=str.lower)
        self._refill_combo(self._blueprints_mission_combo, missions)
        # Scalar facet combos.
        for attr, combo in self._blueprints_facet_combos.items():
            values = sorted({
                v for name in self._blueprint_meta
                if (v := self._facet_value(name, attr)) is not None
            }, key=lambda v: self._facet_sort_key(attr, v))
            self._refill_combo(combo, values)

    @staticmethod
    def _refill_combo(combo, values) -> None:
        """Rebuild *combo* as [Any, *values] preserving the prior selection."""
        prior = combo.currentData()
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(tr("enhancements.blueprints_facet_any"), None)
        for v in values:
            combo.addItem(v, v)
        idx = combo.findData(prior)
        combo.setCurrentIndex(idx if idx >= 0 else 0)
        combo.blockSignals(False)

    def _make_blueprint_item(self, name: str) -> QListWidgetItem:
        """A list row whose display text is the name (or, with the "show
        tags" toggle on, the item's tagged item_Name value), canonical name
        in UserRole (so filters/moves never depend on display text), and a
        tooltip summarizing the item's mission(s) and component attributes."""
        meta = self._blueprint_meta.get(name)
        display = name
        if AppSettings.get_blueprint_show_tags() and meta is not None and meta.tagged_name:
            display = meta.tagged_name
        item = QListWidgetItem(display)
        item.setData(Qt.ItemDataRole.UserRole, name)
        if meta is not None:
            bits = []
            attrs = " ".join(p for p in (meta.type, meta.cls, meta.size, meta.grade) if p)
            if attrs:
                bits.append(attrs)
            if meta.missions:
                bits.append(tr("enhancements.blueprints_tooltip_missions",
                               missions=", ".join(sorted(meta.missions))))
            if bits:
                item.setToolTip("\n".join(bits))
        return item

    def _render_blueprint_lists(self) -> None:
        """Repopulate both lists from the metadata + the persisted owned set,
        preserving the filters and not re-entering the move handlers."""
        owned = AppSettings.get_owned_items()
        available = self._available_blueprints(self._blueprint_meta, owned)
        owned_sorted = sorted(owned, key=str.lower)

        for lst, names in (
            (self._blueprints_available_list, available),
            (self._blueprints_owned_list, owned_sorted),
        ):
            lst.blockSignals(True)
            lst.clear()
            for name in names:
                lst.addItem(self._make_blueprint_item(name))
            lst.blockSignals(False)

        self._refilter_blueprints_available()

        # Empty state: no metadata and nothing owned -> guide the user to
        # generate mission enhancements first; hide the (useless) controls.
        has_content = bool(self._blueprint_meta) or bool(owned)
        self._blueprints_empty_note.setVisible(not has_content)
        for w in (
            self._blueprints_search, self._blueprints_show_tags,
            self._blueprints_mission_label, self._blueprints_mission_combo,
            self._blueprints_filter_note,
            self._blueprints_available_list, self._blueprints_owned_list,
            self._blueprints_add_btn, self._blueprints_remove_btn,
            self._blueprints_available_label, self._blueprints_owned_label,
            *self._blueprints_facet_combos.values(),
            *self._blueprints_facet_labels.values(),
        ):
            w.setVisible(has_content)

    def _blueprint_item_visible(self, name: str) -> bool:
        """True if *name* passes the keyword, mission, and facet filters.

        An item with no value for a facet is hidden only when that facet is set
        to a specific value (not "Any") — so untyped items stay visible until a
        component facet is actually chosen.
        """
        kw = self._blueprints_search.text().strip().lower()
        if kw and kw not in name.lower():
            return False
        mission = self._blueprints_mission_combo.currentData()
        if mission is not None:
            item = self._blueprint_meta.get(name)
            missions = getattr(item, "missions", ()) if item is not None else ()
            if mission not in missions:
                return False
        for attr, combo in self._blueprints_facet_combos.items():
            sel = combo.currentData()
            if sel is not None and self._facet_value(name, attr) != sel:
                return False
        return True

    def _refilter_blueprints_available(self, *_args) -> None:
        """Hide available rows that don't pass the current filters."""
        lst = self._blueprints_available_list
        for i in range(lst.count()):
            item = lst.item(i)
            name = item.data(Qt.ItemDataRole.UserRole)
            item.setHidden(not self._blueprint_item_visible(name))

    def _selected_names(self, lst) -> list:
        return [it.data(Qt.ItemDataRole.UserRole) for it in lst.selectedItems()]

    def _on_blueprints_show_tags_toggled(self, checked: bool) -> None:
        """Persist the show-tags display toggle and re-render (#221)."""
        AppSettings.set_blueprint_show_tags(checked)
        self._render_blueprint_lists()

    def _own_selected_blueprints(self) -> None:
        """Move every selected available item into the owned set (one write)."""
        names = self._selected_names(self._blueprints_available_list)
        if not names:
            return
        owned = AppSettings.get_owned_items()
        owned.update(names)
        AppSettings.set_owned_items(owned)
        self._render_blueprint_lists()
        self.owned_items_changed.emit()
        self.mark_owned_dirty()

    def _unown_selected_blueprints(self) -> None:
        """Move every selected owned item back to available (one write)."""
        names = self._selected_names(self._blueprints_owned_list)
        if not names:
            return
        owned = AppSettings.get_owned_items()
        owned.difference_update(names)
        AppSettings.set_owned_items(owned)
        self._render_blueprint_lists()
        self.owned_items_changed.emit()
        self.mark_owned_dirty()

    # ── Apply Owned Tags dirty-tracking ──────────────────────────────────────
    # Mirrors the Enhancements tab's Generate Enhancements / Save Tag Changes
    # pattern: the button greys out once its own click clears the dirty flag,
    # and lights back up the moment the Owned set changes again — from the
    # arrow buttons above, or a log scan (MainWindow calls mark_owned_dirty()
    # after merging newly-found blueprints, since that path bypasses this
    # tab's own move methods).

    def _set_owned_btn_dirty(self, dirty: bool) -> None:
        """Single chokepoint for the button's enabled state + tooltip so the
        two can never drift apart."""
        self._owned_dirty = dirty
        self._apply_owned_btn.setEnabled(dirty)
        self._apply_owned_btn.setToolTip(
            tr("blueprint_tracker.apply_owned_tag_tooltip") if dirty
            else tr("blueprint_tracker.apply_owned_tag_tooltip_disabled")
        )

    def mark_owned_dirty(self) -> None:
        """Public: light the Apply Owned Tags button back up. Called from
        this tab's own arrow-button moves, and by MainWindow after a log
        scan merges newly-found blueprints into the owned set."""
        self._set_owned_btn_dirty(True)

    def _on_apply_owned_clicked(self) -> None:
        self.apply_owned_requested.emit()
        self._set_owned_btn_dirty(False)
