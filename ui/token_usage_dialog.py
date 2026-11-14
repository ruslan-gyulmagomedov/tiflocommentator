# -*- coding: utf-8 -*-
"""
Диалоговое окно для просмотра статистики расхода токенов и расчета стоимости по моделям.
Полностью доступно для скринридеров (NVDA, JAWS) и выполнено на PySide6.
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox,
    QAbstractItemView, QDoubleSpinBox, QComboBox, QFrame
)
from core.token_tracker import TokenTracker
from ui.accessible_dialogs import confirm_destructive


class TokenUsageDialog(QDialog):
    """Диалог статистики расхода токенов по моделям и расчета затрат."""

    def __init__(self, config=None, parent=None):
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("Статистика расхода токенов и расходов")
        self.setAccessibleName("Окно статистики расхода токенов и стоимости по моделям")
        self.setWindowFlags(self.windowFlags() | Qt.WindowMaximizeButtonHint | Qt.WindowMinimizeButtonHint)
        self.setMinimumSize(850, 480)
        self.resize(1100, 650)

        self.row_widgets = []
        self.init_ui()
        self.load_data()

    def showEvent(self, event):
        super().showEvent(event)
        self.showMaximized()

    def init_ui(self):
        self.setStyleSheet("""
            QDialog { background-color: #181820; color: #EEEEEE; }
            QLabel { color: #EEEEEE; font-size: 13px; }
            QTableWidget {
                background-color: #20202c; color: #FFFFFF; gridline-color: #3b3b4f;
                font-size: 13px; selection-background-color: #005544; selection-color: #FFFFFF;
                border: 1px solid #444455;
            }
            QHeaderView::section {
                background-color: #2b2b3b; color: #00FFCC; padding: 6px;
                font-weight: bold; font-size: 12px; border: 1px solid #3b3b4f;
            }
            QPushButton {
                background-color: #2b2b3b; color: #EEEEEE; border: 1px solid #555566;
                padding: 7px 15px; border-radius: 4px; font-size: 13px; font-weight: bold; min-height: 28px;
            }
            QPushButton:hover { background-color: #005544; color: #00FFCC; border-color: #00FFCC; }
            QPushButton:focus { border: 2px solid #FFFF00; }
            QDoubleSpinBox, QComboBox {
                background-color: #16161e; color: #00FFCC; border: 1px solid #555566;
                padding: 3px 5px; font-size: 13px; font-weight: bold;
            }
            QDoubleSpinBox:focus, QComboBox:focus { border: 2px solid #FFFF00; }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        header_lbl = QLabel("📊 Статистика расхода входящих и исходящих токенов по моделям", self)
        font_hdr = QFont()
        font_hdr.setPointSize(14)
        font_hdr.setBold(True)
        header_lbl.setFont(font_hdr)
        header_lbl.setStyleSheet("color: #00FFCC; margin-bottom: 2px;")
        layout.addWidget(header_lbl)

        desc_lbl = QLabel(
            "В таблице показаны только те модели, к которым производились запросы с момента последнего сброса.\n"
            "Вы можете указать цены за токены в удобной для вас валюте для расчета расходов.",
            self
        )
        desc_lbl.setWordWrap(True)
        desc_lbl.setStyleSheet("color: #AAAAAA; font-size: 12px;")
        layout.addWidget(desc_lbl)

        self.table = QTableWidget(self)
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels([
            "Модель", "Входящие токены", "Исходящие токены", "Тариф за",
            "Цена входящих", "Цена исходящих", "Стоимость"
        ])
        self.table.setAccessibleName("Таблица моделей и расхода токенов")
        self.table.setAccessibleDescription(
            "Стрелки перемещают по строкам и столбцам. Tab переводит фокус к следующему элементу окна."
        )
        # Иначе Tab перебирает ячейки и фокус скринридера застревает в таблице.
        self.table.setTabKeyNavigation(False)
        self.table.setFocusPolicy(Qt.StrongFocus)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        for idx in range(1, 6):
            header.setSectionResizeMode(idx, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.ResizeToContents)
        layout.addWidget(self.table, 1)

        self.frame_total = QFrame(self)
        self.frame_total.setStyleSheet("background-color: #222230; border: 1px solid #44445f; border-radius: 6px; padding: 6px;")
        total_layout = QVBoxLayout(self.frame_total)
        total_layout.setContentsMargins(10, 8, 10, 8)

        self.lbl_total = QLabel("Итого: 0.00", self.frame_total)
        font_total = QFont()
        font_total.setPointSize(13)
        font_total.setBold(True)
        self.lbl_total.setFont(font_total)
        self.lbl_total.setWordWrap(True)
        self.lbl_total.setAccessibleName("Итоговая сумма расходов")
        total_layout.addWidget(self.lbl_total)
        layout.addWidget(self.frame_total, 0)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        self.btn_reset = QPushButton("🗑️ Очистить статистику", self)
        self.btn_reset.setAccessibleName("Очистить статистику расхода токенов")
        self.btn_reset.setStyleSheet("QPushButton { color: #FF7777; border-color: #AA4444; } QPushButton:hover { background-color: #661111; color: #FFFFFF; }")
        self.btn_reset.clicked.connect(self.on_reset_clicked)
        btn_layout.addWidget(self.btn_reset)

        btn_layout.addStretch()

        self.btn_save = QPushButton("💾 Сохранить цены", self)
        self.btn_save.setAccessibleName("Сохранить введенные цены")
        self.btn_save.clicked.connect(self.save_prices)
        btn_layout.addWidget(self.btn_save)

        self.btn_close = QPushButton("Закрыть", self)
        self.btn_close.setAccessibleName("Закрыть окно статистики")
        self.btn_close.setDefault(True)
        self.btn_close.clicked.connect(self.accept)
        btn_layout.addWidget(self.btn_close)

        layout.addLayout(btn_layout, 0)
        QShortcut(QKeySequence("Escape"), self, self.accept)


    def load_data(self):
        """Загружает данные об использовании моделей и заполняет таблицу."""
        usage_data = TokenTracker.get_tracked_usage()
        self.table.setRowCount(0)
        self.row_widgets = []

        if not usage_data:
            self.lbl_total.setText("С момента последнего сброса запросы к моделям ещё не выполнялись. Статистика пуста.")
            self.lbl_total.setStyleSheet("color: #AAAAAA; font-weight: normal;")
            self.lbl_total.setAccessibleDescription("Статистика пуста.")
            return

        for row_idx, (m_name, m_info) in enumerate(usage_data.items()):
            self.table.insertRow(row_idx)

            item_name = QTableWidgetItem(m_name)
            item_name.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            font_b = QFont()
            font_b.setBold(True)
            item_name.setFont(font_b)
            self.table.setItem(row_idx, 0, item_name)

            in_tok = m_info.get("input_tokens", 0)
            item_in = QTableWidgetItem(f"{in_tok:,}".replace(",", " "))
            item_in.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            item_in.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.table.setItem(row_idx, 1, item_in)

            out_tok = m_info.get("output_tokens", 0)
            item_out = QTableWidgetItem(f"{out_tok:,}".replace(",", " "))
            item_out.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            item_out.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.table.setItem(row_idx, 2, item_out)

            combo_unit = QComboBox(self.table)
            combo_unit.addItem("за 1 000 000 (1M)", 1000000)
            combo_unit.addItem("за 1 000 (1K)", 1000)
            combo_unit.addItem("за 1 токен", 1)
            saved_unit = m_info.get("unit", 1000000)
            idx_unit = combo_unit.findData(saved_unit)
            if idx_unit >= 0:
                combo_unit.setCurrentIndex(idx_unit)
            combo_unit.setAccessibleName(f"Единица тарифа для модели {m_name}")
            combo_unit.currentIndexChanged.connect(self.recalculate_totals)
            self.table.setCellWidget(row_idx, 3, combo_unit)

            spin_price_in = QDoubleSpinBox(self.table)
            spin_price_in.setDecimals(6)
            spin_price_in.setRange(0.0, 9999999.0)
            spin_price_in.setSingleStep(0.05)
            p_in = m_info.get("price_input")
            if p_in is not None:
                spin_price_in.setValue(float(p_in))
            else:
                spin_price_in.setValue(0.0)
                spin_price_in.lineEdit().clear()
            spin_price_in.setAccessibleName(f"Цена входящих токенов для модели {m_name}")
            spin_price_in.valueChanged.connect(self.recalculate_totals)
            self.table.setCellWidget(row_idx, 4, spin_price_in)

            spin_price_out = QDoubleSpinBox(self.table)
            spin_price_out.setDecimals(6)
            spin_price_out.setRange(0.0, 9999999.0)
            spin_price_out.setSingleStep(0.1)
            p_out = m_info.get("price_output")
            if p_out is not None:
                spin_price_out.setValue(float(p_out))
            else:
                spin_price_out.setValue(0.0)
                spin_price_out.lineEdit().clear()
            spin_price_out.setAccessibleName(f"Цена исходящих токенов для модели {m_name}")
            spin_price_out.valueChanged.connect(self.recalculate_totals)
            self.table.setCellWidget(row_idx, 5, spin_price_out)

            item_cost_total = QTableWidgetItem("0.00")
            item_cost_total.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            item_cost_total.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            font_tot = QFont()
            font_tot.setBold(True)
            item_cost_total.setFont(font_tot)
            self.table.setItem(row_idx, 6, item_cost_total)

            self.row_widgets.append({
                "model_name": m_name,
                "input_tokens": in_tok,
                "output_tokens": out_tok,
                "combo_unit": combo_unit,
                "spin_price_in": spin_price_in,
                "spin_price_out": spin_price_out,
                "item_cost_total": item_cost_total
            })

        self.recalculate_totals()

    def recalculate_totals(self):
        """Пересчитывает расходы по каждой строке и итоговую сумму."""
        grand_total = 0.0
        all_prices_specified = True
        has_any_models = len(self.row_widgets) > 0

        for row_idx, r in enumerate(self.row_widgets):
            m_name = r["model_name"]
            in_tok = r["input_tokens"]
            out_tok = r["output_tokens"]
            unit = float(r["combo_unit"].currentData() or 1000000)

            spin_in = r["spin_price_in"]
            spin_out = r["spin_price_out"]

            raw_txt_in = spin_in.lineEdit().text().strip()
            raw_txt_out = spin_out.lineEdit().text().strip()

            price_in_val = spin_in.value() if raw_txt_in else None
            price_out_val = spin_out.value() if raw_txt_out else None

            if (in_tok > 0 and price_in_val is None) or (out_tok > 0 and price_out_val is None):
                all_prices_specified = False

            cost_in = ((in_tok / unit) * price_in_val) if price_in_val is not None else 0.0
            cost_out = ((out_tok / unit) * price_out_val) if price_out_val is not None else 0.0
            model_total = cost_in + cost_out
            grand_total += model_total

            txt_model_tot = f"{model_total:,.4f}".replace(",", " ")
            r["item_cost_total"].setText(txt_model_tot)

        if not has_any_models:
            self.lbl_total.setText("С момента последнего сброса запросы к моделям ещё не выполнялись. Статистика пуста.")
            self.lbl_total.setStyleSheet("color: #AAAAAA; font-weight: normal;")
            self.lbl_total.setAccessibleDescription("Статистика пуста.")
            return

        formatted_total = f"{grand_total:,.4f}".replace(",", " ")

        if all_prices_specified:
            self.lbl_total.setText(f"Итого: {formatted_total}")
            self.lbl_total.setStyleSheet("color: #00FFCC; font-weight: bold;")
            self.lbl_total.setAccessibleDescription(f"Итоговая сумма: {formatted_total}")
        else:
            self.lbl_total.setText(f"⚠️ Внимание! Не все цены указаны! По текущим данным, стоимость не менее {formatted_total}")
            self.lbl_total.setStyleSheet("color: #FFCC00; font-weight: bold;")
            self.lbl_total.setAccessibleDescription(f"Предупреждение: Не все цены указаны. По текущим данным, стоимость не менее {formatted_total}")

    def save_prices(self):
        """Сохраняет введенные цены и единицы тарифа в Settings.ini."""
        for r in self.row_widgets:
            m_name = r["model_name"]
            unit = int(r["combo_unit"].currentData() or 1000000)
            spin_in = r["spin_price_in"]
            spin_out = r["spin_price_out"]

            raw_txt_in = spin_in.lineEdit().text().strip()
            raw_txt_out = spin_out.lineEdit().text().strip()

            p_in = spin_in.value() if raw_txt_in else None
            p_out = spin_out.value() if raw_txt_out else None

            TokenTracker.set_model_prices(m_name, p_in, p_out, unit)

    def on_reset_clicked(self):
        """Запрашивает подтверждение и выполняет сброс статистики расходов."""
        confirm = confirm_destructive(
            self,
            "Сброс статистики",
            "Сбросить всю накопленную статистику расхода токенов?\n\n"
            "Список использованных моделей и счетчики токенов будут очищены.\n"
            "Это действие необратимо.",
            accept_text="Сбросить статистику",
        )
        if confirm:
            TokenTracker.reset_usage()
            self.load_data()
            QMessageBox.information(
                self,
                "Статистика очищена",
                "Статистика расхода токенов успешно сброшена."
            )

    def accept(self):
        """Сохраняет цены при закрытии диалога."""
        self.save_prices()
        super().accept()

