#!/usr/bin/env python3
import sys
import sqlite3
import json
import os
import csv

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, Gio, GLib, Gdk

CONFIG_DIR = os.path.expanduser("~/.config/library_manager")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")

# Column Key Definition Map (17 columns total)
ALL_COLUMNS = [
    ("id", "ID", 0),
    ("title", "Title", 1),
    ("author", "Author", 2),
    ("subtitle", "Subtitle", 3),
    ("shelf", "Shelf", 4),
    ("shelf_pos", "Position on Shelf", 5),
    ("status", "Status", 6),
    ("publisher", "Publisher", 7),
    ("pub_year", "Publication Year", 8),
    ("edition_year", "Edition Year", 9),
    ("series_name", "Series Name", 10),
    ("volume", "Volume", 11),
    ("genre", "Genre", 12),
    ("subject", "Subject", 13),
    ("isbn", "ISBN", 14),
    ("pages", "Pages", 15),
    ("language", "Language", 16)
]

DEFAULT_COLUMN_KEYS = [c[0] for c in ALL_COLUMNS]

# Mapping Hungarian export field names to database schema columns
CSV_COLUMN_MAP = {
    'id': 'id',
    'azonosito': 'id',
    'cim': 'title',
    'title': 'title',
    'szerzo': 'author',
    'author': 'author',
    'alcim': 'subtitle',
    'subtitle': 'subtitle',
    'kiado': 'publisher',
    'publisher': 'publisher',
    'kiadas': 'pub_year',
    'pub_year': 'pub_year',
    'kiadas_datuma': 'edition_year',
    'edition_year': 'edition_year',
    'sorozat_neve': 'series_name',
    'series_name': 'series_name',
    'kotetszam': 'volume',
    'volume': 'volume',
    'mufaj_nev': 'genre',
    'mufaj': 'genre',
    'genre': 'genre',
    'targykor_nev': 'subject',
    'subject': 'subject',
    'polc': 'shelf',
    'shelf': 'shelf',
    'helye_polcon': 'shelf_pos',
    'shelf_pos': 'shelf_pos',
    'isbn': 'isbn',
    'hossz': 'pages',
    'pages': 'pages',
    'nyelv': 'language',
    'language': 'language',
    'kolcsonadva': 'borrowed',
    'borrowed': 'borrowed',
    'tartalom': 'summary',
    'summary': 'summary'
}

# Searchable properties list
SEARCHABLE_PROPERTIES = [
    ("title", "Title"),
    ("author", "Author"),
    ("subtitle", "Subtitle"),
    ("series_name", "Series Name"),
    ("publisher", "Publisher"),
    ("genre", "Genre"),
    ("subject", "Subject"),
    ("isbn", "ISBN"),
    ("shelf", "Shelf Position"),
    ("summary", "Summary")
]


def get_db_connection(db_path, timeout=20.0):
    """Return a SQLite connection configured to wait for locks and use WAL mode."""
    conn = sqlite3.connect(db_path, timeout=timeout)
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn


def safe_markup(text):
    """Safely escape text for GTK Pango markup to prevent & errors."""
    if text is None:
        return "N/A"
    return GLib.markup_escape_text(str(text))


def get_saved_db_path():
    """Retrieve saved DB path from config file or default."""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                data = json.load(f)
                return data.get("db_path")
        except Exception:
            pass
    return None


def save_db_path(db_path):
    """Save selected DB path to user configuration file."""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump({"db_path": db_path}, f)


def init_db(db_path):
    """Initialize database tables, migrate new columns if missing, and seed sample data."""
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS books (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                author TEXT,
                subtitle TEXT,
                publisher TEXT,
                pub_year INTEGER,
                edition_year INTEGER,
                series_name TEXT,
                volume INTEGER,
                genre TEXT,
                subject TEXT,
                shelf TEXT,
                shelf_pos TEXT,
                isbn TEXT,
                pages INTEGER,
                language TEXT,
                borrowed INTEGER DEFAULT 0,
                summary TEXT
            )
        """)

        cursor.execute("PRAGMA table_info(books)")
        existing_cols = [col[1] for col in cursor.fetchall()]
        if "edition_year" not in existing_cols:
            cursor.execute("ALTER TABLE books ADD COLUMN edition_year INTEGER")
        if "series_name" not in existing_cols:
            cursor.execute("ALTER TABLE books ADD COLUMN series_name TEXT")
        if "volume" not in existing_cols:
            cursor.execute("ALTER TABLE books ADD COLUMN volume INTEGER")
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)

        cursor.execute("SELECT COUNT(*) FROM books")
        if cursor.fetchone()[0] == 0:
            cursor.execute("""
                INSERT INTO books (id, title, author, subtitle, publisher, pub_year, edition_year, series_name, volume, genre, subject, shelf, shelf_pos, isbn, pages, language, borrowed, summary)
                VALUES (1, '1984', 'George Orwell', 'Nineteen Eighty-Four', 'Secker & Warburg', 1949, 2003, 'Orwell Dystopias', 1, 'Dystopian', 'Political Fiction', 'A1', '04', '9780451524935', 328, 'English', 0, 'A dystopian novel following Winston Smith in a totalitarian regime ruled by Big Brother.')
            """)
        conn.commit()


def load_saved_column_order(db_path):
    try:
        with get_db_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM settings WHERE key = 'column_order'")
            row = cursor.fetchone()

            if row and row[0]:
                saved_keys = json.loads(row[0])
                valid_keys = [k for k in saved_keys if any(c[0] == k for c in ALL_COLUMNS)]
                for k in DEFAULT_COLUMN_KEYS:
                    if k not in valid_keys:
                        valid_keys.append(k)
                return valid_keys
    except Exception:
        pass
    return DEFAULT_COLUMN_KEYS.copy()


def save_column_order(db_path, ordered_keys):
    try:
        with get_db_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                ("column_order", json.dumps(ordered_keys))
            )
            conn.commit()
    except Exception:
        pass


class BookDetailsWindow(Adw.Window):
    def __init__(self, parent, db_path, book_id, on_edit_callback=None):
        super().__init__(transient_for=parent, modal=True)
        self.set_title("Book Details")
        self.set_default_size(500, 620)
        
        self.db_path = db_path
        self.book_id = book_id
        self.on_edit_callback = on_edit_callback

        with get_db_connection(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM books WHERE id = ?", (book_id,))
            self.book_data = cursor.fetchone()

        if not self.book_data:
            self.close()
            return

        header = Adw.HeaderBar()
        edit_btn = Gtk.Button(label="Edit")
        edit_btn.add_css_class("suggested-action")
        edit_btn.connect("clicked", self.on_edit)
        header.pack_end(edit_btn)

        page = Adw.PreferencesPage()

        gen_group = Adw.PreferencesGroup(title="General Information")
        page.add(gen_group)
        gen_group.add(Adw.ActionRow(title="ID", subtitle=safe_markup(self.book_data[0])))
        gen_group.add(Adw.ActionRow(title="Title (Cím)", subtitle=safe_markup(self.book_data[1])))
        gen_group.add(Adw.ActionRow(title="Author (Szerző)", subtitle=safe_markup(self.book_data[2])))
        if self.book_data[3]:
            gen_group.add(Adw.ActionRow(title="Subtitle (Alcím)", subtitle=safe_markup(self.book_data[3])))

        loc_group = Adw.PreferencesGroup(title="Shelf Location")
        page.add(loc_group)
        loc_group.add(Adw.ActionRow(title="Shelf (Polc)", subtitle=safe_markup(self.book_data[11])))
        loc_group.add(Adw.ActionRow(title="Position on Shelf (Helye)", subtitle=safe_markup(self.book_data[12])))
        status = "Borrowed (Kölcsönadva)" if self.book_data[16] else "Available on Shelf"
        loc_group.add(Adw.ActionRow(title="Status", subtitle=status))

        pub_group = Adw.PreferencesGroup(title="Publication and Series")
        page.add(pub_group)
        pub_group.add(Adw.ActionRow(title="Publisher (Kiadó)", subtitle=safe_markup(self.book_data[4])))
        pub_group.add(Adw.ActionRow(title="Publication Year", subtitle=safe_markup(self.book_data[5])))
        pub_group.add(Adw.ActionRow(title="Edition Year", subtitle=safe_markup(self.book_data[6])))
        pub_group.add(Adw.ActionRow(title="Series Name", subtitle=safe_markup(self.book_data[7])))
        pub_group.add(Adw.ActionRow(title="Volume", subtitle=safe_markup(self.book_data[8])))
        pub_group.add(Adw.ActionRow(title="Genre (Műfaj)", subtitle=safe_markup(self.book_data[9])))
        pub_group.add(Adw.ActionRow(title="Subject (Tárgykör)", subtitle=safe_markup(self.book_data[10])))
        pub_group.add(Adw.ActionRow(title="ISBN", subtitle=safe_markup(self.book_data[13])))
        pub_group.add(Adw.ActionRow(title="Pages", subtitle=safe_markup(self.book_data[14])))
        pub_group.add(Adw.ActionRow(title="Language", subtitle=safe_markup(self.book_data[15])))

        if self.book_data[17]:
            sum_group = Adw.PreferencesGroup(title="Summary (Tartalom)")
            sum_row = Adw.ActionRow(title="Summary", subtitle=safe_markup(self.book_data[17]))
            sum_group.add(sum_row)
            page.add(sum_group)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.append(header)
        box.append(page)
        self.set_content(box)

    def on_edit(self, button):
        self.close()
        if self.on_edit_callback:
            self.on_edit_callback(self.book_id)


class BookDialog(Adw.Window):
    def __init__(self, parent, db_path, book_data=None, on_save_callback=None):
        super().__init__(transient_for=parent, modal=True)
        self.set_title("Edit Book" if book_data else "Add New Book")
        self.set_default_size(500, 620)
        
        self.db_path = db_path
        self.book_id = book_data[0] if book_data else None
        self.on_save_callback = on_save_callback

        header = Adw.HeaderBar()
        save_btn = Gtk.Button(label="Save")
        save_btn.add_css_class("suggested-action")
        save_btn.connect("clicked", self.on_save)
        header.pack_end(save_btn)

        page = Adw.PreferencesPage()

        gen_group = Adw.PreferencesGroup(title="General Information")
        page.add(gen_group)
        self.title_row = Adw.EntryRow(title="Title (Cím)")
        self.author_row = Adw.EntryRow(title="Author (Szerző)")
        self.subtitle_row = Adw.EntryRow(title="Subtitle (Alcím)")
        gen_group.add(self.title_row)
        gen_group.add(self.author_row)
        gen_group.add(self.subtitle_row)

        loc_group = Adw.PreferencesGroup(title="Shelf Location")
        page.add(loc_group)
        self.shelf_row = Adw.EntryRow(title="Shelf (Polc)")
        self.shelf_pos_row = Adw.EntryRow(title="Position on Shelf (Helye)")
        self.borrowed_row = Adw.SwitchRow(title="Borrowed (Kölcsönadva)")
        loc_group.add(self.shelf_row)
        loc_group.add(self.shelf_pos_row)
        loc_group.add(self.borrowed_row)

        pub_group = Adw.PreferencesGroup(title="Publication and Series")
        page.add(pub_group)
        self.publisher_row = Adw.EntryRow(title="Publisher (Kiadó)")
        self.year_row = Adw.EntryRow(title="Publication Year (Kiadási év)")
        self.edition_row = Adw.EntryRow(title="Edition Year (Kiadás éve)")
        self.series_row = Adw.EntryRow(title="Series Name (Sorozat neve)")
        self.volume_row = Adw.EntryRow(title="Volume (Kötetszám)")
        self.genre_row = Adw.EntryRow(title="Genre (Műfaj)")
        self.subject_row = Adw.EntryRow(title="Subject (Tárgykör)")
        self.isbn_row = Adw.EntryRow(title="ISBN")
        self.pages_row = Adw.EntryRow(title="Pages (Hossz)")
        self.lang_row = Adw.EntryRow(title="Language (Nyelv)")
        
        pub_group.add(self.publisher_row)
        pub_group.add(self.year_row)
        pub_group.add(self.edition_row)
        pub_group.add(self.series_row)
        pub_group.add(self.volume_row)
        pub_group.add(self.genre_row)
        pub_group.add(self.subject_row)
        pub_group.add(self.isbn_row)
        pub_group.add(self.pages_row)
        pub_group.add(self.lang_row)

        sum_group = Adw.PreferencesGroup(title="Summary (Tartalom)")
        page.add(sum_group)
        self.summary_row = Adw.EntryRow(title="Summary")
        sum_group.add(self.summary_row)

        if book_data:
            self.title_row.set_text(str(book_data[1] or ""))
            self.author_row.set_text(str(book_data[2] or ""))
            self.subtitle_row.set_text(str(book_data[3] or ""))
            self.publisher_row.set_text(str(book_data[4] or ""))
            self.year_row.set_text(str(book_data[5] or "") if book_data[5] is not None else "")
            self.edition_row.set_text(str(book_data[6] or "") if book_data[6] is not None else "")
            self.series_row.set_text(str(book_data[7] or ""))
            self.volume_row.set_text(str(book_data[8] or "") if book_data[8] is not None else "")
            self.genre_row.set_text(str(book_data[9] or ""))
            self.subject_row.set_text(str(book_data[10] or ""))
            self.shelf_row.set_text(str(book_data[11] or ""))
            self.shelf_pos_row.set_text(str(book_data[12] or ""))
            self.isbn_row.set_text(str(book_data[13] or ""))
            self.pages_row.set_text(str(book_data[14] or "") if book_data[14] is not None else "")
            self.lang_row.set_text(str(book_data[15] or ""))
            self.borrowed_row.set_active(bool(book_data[16]))
            self.summary_row.set_text(str(book_data[17] or ""))

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.append(header)
        box.append(page)
        self.set_content(box)

    def on_save(self, button):
        title = self.title_row.get_text().strip()
        if not title:
            return

        author = self.author_row.get_text().strip()
        subtitle = self.subtitle_row.get_text().strip()
        publisher = self.publisher_row.get_text().strip()
        pub_year = int(self.year_row.get_text()) if self.year_row.get_text().isdigit() else None
        edition_year = int(self.edition_row.get_text()) if self.edition_row.get_text().isdigit() else None
        series_name = self.series_row.get_text().strip()
        volume = int(self.volume_row.get_text()) if self.volume_row.get_text().isdigit() else None
        genre = self.genre_row.get_text().strip()
        subject = self.subject_row.get_text().strip()
        shelf = self.shelf_row.get_text().strip()
        shelf_pos = self.shelf_pos_row.get_text().strip()
        isbn = self.isbn_row.get_text().strip()
        pages = int(self.pages_row.get_text()) if self.pages_row.get_text().isdigit() else None
        lang = self.lang_row.get_text().strip()
        borrowed = 1 if self.borrowed_row.get_active() else 0
        summary = self.summary_row.get_text().strip()

        with get_db_connection(self.db_path) as conn:
            cursor = conn.cursor()
            if self.book_id:
                cursor.execute("""
                    UPDATE books SET title=?, author=?, subtitle=?, publisher=?, pub_year=?, 
                    edition_year=?, series_name=?, volume=?, genre=?, subject=?, shelf=?, 
                    shelf_pos=?, isbn=?, pages=?, language=?, borrowed=?, summary=?
                    WHERE id=?
                """, (title, author, subtitle, publisher, pub_year, edition_year, series_name, volume, genre, subject, shelf, shelf_pos, isbn, pages, lang, borrowed, summary, self.book_id))
            else:
                cursor.execute("""
                    INSERT INTO books (title, author, subtitle, publisher, pub_year, edition_year, series_name, volume, genre, subject, shelf, shelf_pos, isbn, pages, language, borrowed, summary)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (title, author, subtitle, publisher, pub_year, edition_year, series_name, volume, genre, subject, shelf, shelf_pos, isbn, pages, lang, borrowed, summary))
            conn.commit()

        if self.on_save_callback:
            self.on_save_callback()
        self.close()


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, db_path, **kwargs):
        super().__init__(**kwargs)
        self.db_path = db_path
        self.set_title("Library Manager")
        self.set_default_size(1180, 700)

        self.zoom_level = 1.0
        
        self.css_provider = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            self.css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        self.toast_overlay = Adw.ToastOverlay()

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        header = Adw.HeaderBar()
        
        left_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)

        add_btn = Gtk.Button(icon_name="list-add-symbolic")
        add_btn.set_tooltip_text("Add New Book")
        add_btn.connect("clicked", self.on_add_book)
        left_box.append(add_btn)

        import_btn = Gtk.Button(icon_name="document-open-symbolic")
        import_btn.set_tooltip_text("Import Books from CSV File")
        import_btn.connect("clicked", self.on_import_csv_clicked)
        left_box.append(import_btn)

        header.pack_start(left_box)

        right_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)

        self.db_btn = Gtk.Button(icon_name="drive-harddisk-symbolic")
        db_filename = os.path.basename(self.db_path)
        self.db_btn.set_label(f" {db_filename}")
        self.db_btn.set_tooltip_text(f"Current Database: {self.db_path}\nClick to change or create new database.")
        self.db_btn.connect("clicked", self.on_change_db_clicked)
        right_box.append(self.db_btn)

        zoom_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        zoom_box.add_css_class("linked")

        zoom_out_btn = Gtk.Button(icon_name="zoom-out-symbolic")
        zoom_out_btn.set_tooltip_text("Zoom Out Table Text (Ctrl+-)")
        zoom_out_btn.connect("clicked", lambda x: self.change_zoom(-0.1))

        self.zoom_reset_btn = Gtk.Button(label="100%")
        self.zoom_reset_btn.set_tooltip_text("Reset Zoom Level (Ctrl+0)")
        self.zoom_reset_btn.connect("clicked", lambda x: self.reset_zoom())

        zoom_in_btn = Gtk.Button(icon_name="zoom-in-symbolic")
        zoom_in_btn.set_tooltip_text("Zoom In Table Text (Ctrl++)")
        zoom_in_btn.connect("clicked", lambda x: self.change_zoom(0.1))

        zoom_box.append(zoom_out_btn)
        zoom_box.append(self.zoom_reset_btn)
        zoom_box.append(zoom_in_btn)

        right_box.append(zoom_box)
        header.pack_end(right_box)
        main_box.append(header)

        # Extended Search Bar Area
        search_clamp = Adw.Clamp(maximum_size=680, margin_top=12, margin_bottom=12)
        search_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)

        self.search_entry = Gtk.SearchEntry(placeholder_text="Search books...")
        self.search_entry.set_hexpand(True)
        self.search_entry.connect("search-changed", self.on_search_changed)

        # Dropdown filter menu button
        self.filter_popover = Gtk.Popover()
        self.search_check_buttons = {}
        
        popover_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        popover_box.set_margin_top(10)
        popover_box.set_margin_bottom(10)
        popover_box.set_margin_start(12)
        popover_box.set_margin_end(12)

        popover_title = Gtk.Label(label="Search in Properties")
        popover_title.add_css_class("heading")
        popover_title.set_halign(Gtk.Align.START)
        popover_box.append(popover_title)

        grid = Gtk.Grid(column_spacing=12, row_spacing=6)
        
        # Build property checkboxes grid
        for idx, (prop_key, prop_label) in enumerate(SEARCHABLE_PROPERTIES):
            check = Gtk.CheckButton(label=prop_label)
            check.set_active(True) # Checked by default
            check.connect("toggled", lambda cb: self.load_books(self.search_entry.get_text().strip()))
            self.search_check_buttons[prop_key] = check
            
            row = idx // 2
            col = idx % 2
            grid.attach(check, col, row, 1, 1)

        popover_box.append(grid)

        # Select All / Clear All action bar
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        btn_box.set_margin_top(6)
        
        select_all_btn = Gtk.Button(label="Select All")
        select_all_btn.connect("clicked", lambda b: self.set_all_search_filters(True))
        
        clear_all_btn = Gtk.Button(label="Clear All")
        clear_all_btn.connect("clicked", lambda b: self.set_all_search_filters(False))

        btn_box.append(select_all_btn)
        btn_box.append(clear_all_btn)
        popover_box.append(btn_box)

        self.filter_popover.set_child(popover_box)

        filter_menu_btn = Gtk.MenuButton()
        filter_menu_btn.set_icon_name("pan-down-symbolic")
        filter_menu_btn.set_tooltip_text("Select search target properties")
        filter_menu_btn.set_popover(self.filter_popover)

        search_box.append(self.search_entry)
        search_box.append(filter_menu_btn)

        search_clamp.set_child(search_box)
        main_box.append(search_clamp)

        # Table (17 columns)
        self.store = Gtk.ListStore(int, str, str, str, str, str, str, str, str, str, str, str, str, str, str, str, str)
        self.treeview = Gtk.TreeView(model=self.store)
        self.treeview.add_css_class("zoomable-table")
        self.treeview.set_vexpand(True)
        self.treeview.set_hexpand(True)
        self.treeview.connect("row-activated", self.on_row_activated)

        self.columns_dict = {}
        for key, title, col_idx in ALL_COLUMNS:
            renderer = Gtk.CellRendererText()
            column = Gtk.TreeViewColumn(title, renderer, text=col_idx)
            column.set_resizable(True)
            column.set_reorderable(True)
            column.set_sort_column_id(col_idx)
            column.key_name = key
            column.connect("notify::position", self.on_column_reordered)
            self.columns_dict[key] = column

        self.setup_columns()

        action_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10, margin_top=10, margin_bottom=10, margin_start=10, margin_end=10)
        
        view_btn = Gtk.Button(label="View Selected")
        view_btn.connect("clicked", self.on_view_selected)

        edit_btn = Gtk.Button(label="Edit Selected")
        edit_btn.connect("clicked", self.on_edit_book)
        
        delete_btn = Gtk.Button(label="Delete Selected")
        delete_btn.add_css_class("destructive-action")
        delete_btn.connect("clicked", self.on_delete_book)

        action_box.append(view_btn)
        action_box.append(edit_btn)
        action_box.append(delete_btn)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_child(self.treeview)

        main_box.append(scrolled)
        main_box.append(action_box)

        self.toast_overlay.set_child(main_box)
        self.set_content(self.toast_overlay)

        key_controller = Gtk.EventControllerKey()
        key_controller.connect("key-pressed", self.on_key_pressed)
        self.add_controller(key_controller)

        self.update_css_zoom()
        self.load_books()

    def set_all_search_filters(self, state):
        for check in self.search_check_buttons.values():
            check.set_active(state)
        self.load_books(self.search_entry.get_text().strip())

    def setup_columns(self):
        for col in list(self.treeview.get_columns()):
            self.treeview.remove_column(col)
        
        saved_key_order = load_saved_column_order(self.db_path)
        for key in saved_key_order:
            if key in self.columns_dict:
                self.treeview.append_column(self.columns_dict[key])

    def set_new_db_path(self, new_path):
        self.db_path = new_path
        save_db_path(new_path)
        init_db(new_path)
        self.db_btn.set_label(f" {os.path.basename(new_path)}")
        self.db_btn.set_tooltip_text(f"Current Database: {new_path}\nClick to change or create new database.")
        self.setup_columns()
        self.load_books()

    def on_change_db_clicked(self, button):
        dialog = Gtk.FileChooserNative(
            title="Open or Create Database File",
            transient_for=self,
            action=Gtk.FileChooserAction.OPEN
        )
        
        filter_db = Gtk.FileFilter()
        filter_db.set_name("SQLite Databases (*.db, *.sqlite)")
        filter_db.add_pattern("*.db")
        filter_db.add_pattern("*.sqlite")
        dialog.add_filter(filter_db)

        def on_response(native, response):
            if response == Gtk.ResponseType.ACCEPT:
                file = native.get_file()
                if file:
                    path = file.get_path()
                    self.set_new_db_path(path)

        dialog.connect("response", on_response)
        dialog.show()

    def on_import_csv_clicked(self, button):
        dialog = Gtk.FileChooserNative(
            title="Import Books from CSV File",
            transient_for=self,
            action=Gtk.FileChooserAction.OPEN
        )
        
        filter_csv = Gtk.FileFilter()
        filter_csv.set_name("CSV Files (*.csv)")
        filter_csv.add_pattern("*.csv")
        dialog.add_filter(filter_csv)

        def on_response(native, response):
            if response == Gtk.ResponseType.ACCEPT:
                file = native.get_file()
                if file:
                    path = file.get_path()
                    self.import_csv_file(path)

        dialog.connect("response", on_response)
        dialog.show()

    def import_csv_file(self, csv_path):
        imported_count = 0
        try:
            with open(csv_path, mode='r', encoding='utf-8-sig', errors='replace') as f:
                reader = csv.DictReader(f)
                if not reader.fieldnames:
                    return

                db_cols = []
                csv_cols = []
                for header in reader.fieldnames:
                    clean_h = header.strip().lower()
                    if clean_h in CSV_COLUMN_MAP:
                        target_col = CSV_COLUMN_MAP[clean_h]
                        if target_col not in db_cols:
                            db_cols.append(target_col)
                            csv_cols.append(header)

                if not db_cols or ('title' not in db_cols):
                    self.toast_overlay.add_toast(Adw.Toast(title="CSV must contain 'title' or 'cim' header."))
                    return

                query = f"INSERT INTO books ({', '.join(db_cols)}) VALUES ({', '.join(['?'] * len(db_cols))})"

                rows_to_insert = []
                for row in reader:
                    values = []
                    row_title = None

                    for idx, csv_col in enumerate(csv_cols):
                        target_col = db_cols[idx]
                        val = row.get(csv_col, "").strip()

                        if target_col == 'title':
                            row_title = val

                        values.append(val if val != "" else None)

                    if all(v is None for v in values):
                        continue

                    if not row_title:
                        title_idx = db_cols.index('title')
                        values[title_idx] = "Untitled Book"

                    rows_to_insert.append(values)

                if not rows_to_insert:
                    self.toast_overlay.add_toast(Adw.Toast(title="No valid records found in CSV file."))
                    return

                with get_db_connection(self.db_path) as conn:
                    cursor = conn.cursor()
                    cursor.executemany(query, rows_to_insert)
                    conn.commit()
                    imported_count = len(rows_to_insert)

            self.load_books()
            self.toast_overlay.add_toast(Adw.Toast(title=f"Successfully imported {imported_count} book(s) from CSV."))

        except Exception as e:
            self.toast_overlay.add_toast(Adw.Toast(title=f"Error importing CSV: {str(e)}"))

    def on_column_reordered(self, column, param_spec):
        current_cols = self.treeview.get_columns()
        ordered_keys = [col.key_name for col in current_cols if hasattr(col, "key_name")]
        if ordered_keys:
            save_column_order(self.db_path, ordered_keys)

    def change_zoom(self, delta):
        self.zoom_level = max(0.7, min(2.0, self.zoom_level + delta))
        self.update_css_zoom()

    def reset_zoom(self):
        self.zoom_level = 1.0
        self.update_css_zoom()

    def update_css_zoom(self):
        font_size_pt = round(11 * self.zoom_level, 1)
        padding_px = max(4, int(6 * self.zoom_level))
        css_data = f"""
            treeview.zoomable-table {{
                font-size: {font_size_pt}pt;
            }}
            treeview.zoomable-table cell {{
                padding: {padding_px}px;
            }}
        """
        self.css_provider.load_from_data(css_data.encode('utf-8'))
        self.zoom_reset_btn.set_label(f"{int(self.zoom_level * 100)}%")

    def on_key_pressed(self, controller, keyval, keycode, state):
        ctrl_pressed = (state & Gdk.ModifierType.CONTROL_MASK) != 0
        if ctrl_pressed:
            if keyval in (Gdk.KEY_plus, Gdk.KEY_equal, Gdk.KEY_KP_Add):
                self.change_zoom(0.1)
                return True
            elif keyval in (Gdk.KEY_minus, Gdk.KEY_KP_Subtract):
                self.change_zoom(-0.1)
                return True
            elif keyval in (Gdk.KEY_0, Gdk.KEY_KP_0):
                self.reset_zoom()
                return True
        return False

    def load_books(self, search_query=""):
        self.store.clear()
        with get_db_connection(self.db_path) as conn:
            cursor = conn.cursor()

            query_sql = """
                SELECT id, title, author, subtitle, shelf, shelf_pos, borrowed, 
                       publisher, pub_year, edition_year, series_name, volume, 
                       genre, subject, isbn, pages, language
                FROM books
            """

            if search_query:
                # Determine active checked search target fields
                active_targets = [prop_key for prop_key, check in self.search_check_buttons.items() if check.get_active()]
                
                if active_targets:
                    q = f"%{search_query}%"
                    where_clauses = [f"{col} LIKE ?" for col in active_targets]
                    query_sql += f" WHERE ({' OR '.join(where_clauses)})"
                    cursor.execute(query_sql, [q] * len(active_targets))
                else:
                    # If all checkboxes are unchecked, return no results
                    return
            else:
                cursor.execute(query_sql)

            for row in cursor.fetchall():
                status_str = "Borrowed" if row[6] else "Available"
                self.store.append([
                    row[0],                           # 0: ID
                    row[1] or "",                     # 1: Title
                    row[2] or "",                     # 2: Author
                    row[3] or "",                     # 3: Subtitle
                    row[4] or "",                     # 4: Shelf
                    row[5] or "",                     # 5: Position on Shelf
                    status_str,                       # 6: Status
                    row[7] or "",                     # 7: Publisher
                    str(row[8]) if row[8] else "",    # 8: Publication Year
                    str(row[9]) if row[9] else "",    # 9: Edition Year
                    row[10] or "",                    # 10: Series Name
                    str(row[11]) if row[11] else "",  # 11: Volume
                    row[12] or "",                    # 12: Genre
                    row[13] or "",                    # 13: Subject
                    row[14] or "",                    # 14: ISBN
                    str(row[15]) if row[15] else "",  # 15: Pages
                    row[16] or ""                     # 16: Language
                ])

    def on_search_changed(self, entry):
        self.load_books(entry.get_text().strip())

    def get_selected_id(self):
        selection = self.treeview.get_selection()
        model, treeiter = selection.get_selected()
        if treeiter:
            return model[treeiter][0]
        return None

    def open_view_dialog(self, book_id):
        dialog = BookDetailsWindow(self, self.db_path, book_id, on_edit_callback=self.open_edit_dialog_by_id)
        dialog.present()

    def open_edit_dialog_by_id(self, book_id):
        with get_db_connection(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, title, author, subtitle, publisher, pub_year, edition_year, 
                       series_name, volume, genre, subject, shelf, shelf_pos, isbn, 
                       pages, language, borrowed, summary 
                FROM books WHERE id = ?
            """, (book_id,))
            book_data = cursor.fetchone()

        if book_data:
            dialog = BookDialog(self, self.db_path, book_data=book_data, on_save_callback=self.load_books)
            dialog.present()

    def on_row_activated(self, treeview, path, column):
        book_id = self.get_selected_id()
        if book_id:
            self.open_view_dialog(book_id)

    def on_view_selected(self, button):
        book_id = self.get_selected_id()
        if book_id:
            self.open_view_dialog(book_id)

    def on_add_book(self, button):
        dialog = BookDialog(self, self.db_path, on_save_callback=self.load_books)
        dialog.present()

    def on_edit_book(self, button):
        book_id = self.get_selected_id()
        if book_id:
            self.open_edit_dialog_by_id(book_id)

    def on_delete_book(self, button):
        book_id = self.get_selected_id()
        if not book_id:
            return

        with get_db_connection(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM books WHERE id = ?", (book_id,))
            conn.commit()

        self.load_books()


class LibraryApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id="com.example.LibraryManager")

    def do_activate(self):
        db_path = get_saved_db_path()

        if not db_path or not os.path.exists(db_path):
            self.show_initial_db_prompt()
        else:
            self.launch_main_window(db_path)

    def show_initial_db_prompt(self):
        win = Adw.Window(application=self, title="Welcome to Library Manager")
        win.set_default_size(500, 640)
        win.set_resizable(True)

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        header = Adw.HeaderBar()
        main_box.append(header)

        page = Adw.StatusPage(
            title="Select Database",
            description="Choose an existing database file or create a new library database.",
            icon_name="drive-harddisk-symbolic"
        )

        button_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        button_box.set_halign(Gtk.Align.CENTER)
        button_box.set_margin_top(18)
        button_box.set_margin_bottom(24)

        browse_btn = Gtk.Button(label="Browse Existing Database...")
        browse_btn.add_css_class("suggested-action")
        browse_btn.add_css_class("pill")

        create_btn = Gtk.Button(label="Create New Database...")
        create_btn.add_css_class("pill")

        button_box.append(browse_btn)
        button_box.append(create_btn)
        page.set_child(button_box)

        main_box.append(page)
        win.set_content(main_box)

        def on_browse_clicked(btn):
            dialog = Gtk.FileChooserNative(
                title="Open Existing Database",
                transient_for=win,
                action=Gtk.FileChooserAction.OPEN
            )
            def on_response(native, response):
                if response == Gtk.ResponseType.ACCEPT:
                    path = native.get_file().get_path()
                    win.close()
                    self.launch_main_window(path)
            dialog.connect("response", on_response)
            dialog.show()

        def on_create_clicked(btn):
            dialog = Gtk.FileChooserNative(
                title="Create New Database File",
                transient_for=win,
                action=Gtk.FileChooserAction.SAVE
            )
            dialog.set_current_name("library.db")
            def on_response(native, response):
                if response == Gtk.ResponseType.ACCEPT:
                    path = native.get_file().get_path()
                    if not path.endswith(".db"):
                        path += ".db"
                    win.close()
                    self.launch_main_window(path)
            dialog.connect("response", on_response)
            dialog.show()

        browse_btn.connect("clicked", on_browse_clicked)
        create_btn.connect("clicked", on_create_clicked)
        win.present()

    def launch_main_window(self, db_path):
        save_db_path(db_path)
        init_db(db_path)
        win = MainWindow(db_path=db_path, application=self)
        win.present()


if __name__ == "__main__":
    app = LibraryApp()
    app.run(sys.argv)