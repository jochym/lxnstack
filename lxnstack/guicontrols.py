# lxnstack is a program to align and stack atronomical images
# Copyright (C) 2013-2015  Maurizio D'Addona <mauritiusdadd@gmail.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import math
import os
from . import paths
import logging

from PyQt5 import Qt, QtCore, QtGui, uic
from PyQt5.QtWidgets import QLineEdit, QStyledItemDelegate, QComboBox
from PyQt5.QtWidgets import QDialog, QDialogButtonBox, QWidget, QProgressBar
from PyQt5.QtWidgets import QApplication, QVBoxLayout, QTableWidget, QTableWidgetItem

from . import translation as tr
from . import plotting
from . import utils
from . import styles
from . import lightcurves as lcurves
from . import colormaps as cmaps
from . import mappedimage
import numpy as np
from . import log

IMAGEVIEWER = "imageviewer"
DIFFERENCEVIEWER = "diffviewer"
PLOTVIEWER = "plotviewer"

READY = 0x0001
UPDATED = 0x0002
NEEDS_IMAGE_UPDATE = 0x0004
NEEDS_FEATURES_UPDATE = 0x0004


class DialogWindow(object):

    def __init__(self, uifile):
        self._dialog = uic.loadUi(
            os.path.join(paths.UI_PATH, uifile))

    def exec_(self):
        return self._dialog.exec_()


class AboutWindow(DialogWindow):

    def __init__(self):
        DialogWindow.__init__(self, 'about_dialog.ui')

        self._dialog.iconLabel.setPixmap(
            QtGui.QPixmap(os.path.join(paths.RESOURCES_PATH,
                                       paths.PROGRAM_NAME+".png")))

    def exec_(self):
        return self._dialog.exec_()


class OptionsDialog(DialogWindow):

    def __init__(self):
        DialogWindow.__init__(self, 'option_dialog.ui')

        self._dialog.refreshPushButton.setIcon(utils.getQIcon("view-refresh"))

        self._stylesheets = styles.enumarateStylesSheet()
        for stylesheet_file in self._stylesheets:
            self._dialog.themeListWidget.addItem(stylesheet_file)

        self._dialog.themeListWidget.currentItemChanged.connect(
            self.setApplicationStyleSheet)

    def setApplicationStyleSheet(self, current, previous):
        stylename = str(current.text())
        try:
            filename = self._stylesheets[stylename]
        except KeyError:
            filename = None
        styles.setApplicationStyleSheet(filename)
        self._current_stylesheet = stylename


class StackingDialog(DialogWindow):

    section_light = 0
    section_bias = 1
    section_dark = 2
    section_flat = 3

    def __init__(self):
        DialogWindow.__init__(self, 'stack_dialog.ui')

    def setSectionEnabled(self, section, val):
        self._dialog.tabWidget.setTabEnabled(section, bool(val))

    def setSectionDisabled(self, section, val):
        self._dialog.tabWidget.setTabEnabled(section, not bool(val))

    def getStackingMethods(self):
        bias_cb = self._dialog.biasStackingMethodComboBox
        dark_cb = self._dialog.darkStackingMethodComboBox
        flat_cb = self._dialog.flatStackingMethodComboBox
        lght_cb = self._dialog.ligthStackingMethodComboBox

        methods = {
            self.section_light: lght_cb.currentIndex(),
            self.section_bias: bias_cb.currentIndex(),
            self.section_dark: dark_cb.currentIndex(),
            self.section_flat: flat_cb.currentIndex(),
        }

        return methods

    def getStackingParameters(self):
        methods = {
            self.section_light: {
                'lk': self._dialog.ligthLKappa.value(),
                'hk': self._dialog.ligthHKappa.value(),
                'iterations': self._dialog.ligthKIters.value(),
                'debayerize_result': True
            },
            self.section_bias: {
                'lk': self._dialog.biasLKappa.value(),
                'hk': self._dialog.biasHKappa.value(),
                'iterations': self._dialog.biasKIters.value(),
                'debayerize_result': False
            },
            self.section_dark: {
                'lk': self._dialog.darkLKappa.value(),
                'hk': self._dialog.darkHKappa.value(),
                'iterations': self._dialog.darkKIters.value(),
                'debayerize_result': False
            },
            self.section_flat: {
                'lk': self._dialog.flatLKappa.value(),
                'hk': self._dialog.flatHKappa.value(),
                'iterations': self._dialog.flatKIters.value(),
                'debayerize_result': False
            },
        }

        return methods

    def getHPCorrectionParameters(self):
        hp_use_smrt = bool(self._dialog.hotSmartGroupBox.isChecked())
        hp_use_glbl = bool(self._dialog.hotGlobalRadioButton.isChecked())
        hp_threshold = self._dialog.hotTrasholdDoubleSpinBox.value()

        hotp_args = {'hp_smart': hp_use_smrt,
                     'hp_global': hp_use_glbl,
                     'hp_threshold': hp_threshold}

        return hotp_args


class AlignmentDialog(DialogWindow):

    def __init__(self):
        DialogWindow.__init__(self, 'align_dialog.ui')

    def getAlign(self):
        align_only = self._dialog.alignOnlyRadioButton.isChecked()
        align_derot = self._dialog.alignDerotateRadioButton.isChecked()
        return bool(align_derot or align_only)

    def getDerotate(self):
        derot_only = self._dialog.derotateOnlyRadioButton.isChecked()
        align_derot = self._dialog.alignDerotateRadioButton.isChecked()
        return bool(align_derot or derot_only)

    def getReset(self):
        return bool(self._dialog.resetRadioButton.isChecked())


class VideSaveDialog(DialogWindow):

    def __init__(self):
        DialogWindow.__init__(self, 'video_dialog.ui')

    def getCodecFCC(self):
        cidx = self._dialog.codecComboBox.currentIndex()
        if cidx == 0:
            fcc_str = 'DIVX'
            # max_res = (4920, 4920)
        elif cidx == 1:
            fcc_str = 'MJPG'
            # max_res = (9840, 9840)
        elif cidx == 1:
            fcc_str = 'U263'
            # max_res = (2048, 1024)
        return fcc_str

    def useCustomSize(self):
        return bool(self._dialog.fullFrameCheckBox.checkState() == 0)

    def getFrameSize(self, wid, hei):
        """
            Returns the new frame size and the zoom factor
        """
        if not self.useCustomSize():
            size = (wid, hei)
            fzoom = 1
        else:
            fh = self._dialog.resSpinBox.value()
            fzoom = float(fh)/float(hei)
            fw = int(wid*fzoom)
            size = (fw, fh)
        return size, fzoom

    def getFps(self):
        return self._dialog.fpsSpinBox.value()

    def getFitLevels(self):
        return bool(self._dialog.fitVideoCheckBox.checkState() == 2)

    def useAligedImages(self):
        return bool(self._dialog.useAligedCheckBox.checkState() == 2)


class SplashScreen(Qt.QObject):

    def __init__(self):

        Qt.QObject.__init__(self)

        splashfile = os.path.join(paths.DATA_PATH, "splashscreen.jpg")

        self._msg = ""
        self._pxm = Qt.QPixmap(splashfile)
        self._qss = Qt.QSplashScreen(self._pxm,
                                     QtCore.Qt.WindowStaysOnTopHint |
                                     QtCore.Qt.X11BypassWindowManagerHint)
        self._progress = QProgressBar(self._qss)

        h = self._pxm.height()
        w = self._pxm.width()

        self._progress.setMaximum(100)
        self._progress.setMinimum(0)
        self._progress.setGeometry(10, h-50, w-20, 20)
        self._progress.setStyleSheet("""
        QSplashScreen QProgressBar {
            border: 1px solid gray;
            border-radius: 0px;
            background-color: black;
            color: white;
            height: 1em;
        }

        QSplashScreen QProgressBar::chunk {
            background-color: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                                       stop: 0 #0A0AFF, stop: 1 #0A0A9B);
            width: 20px;
        }
        """)

        self._qss.show()
        self.processEvents()

    def close(self):
        self.update()
        self._qss.close()

    def setMaximum(self, val):
        self._progress.setMaximum(val)

    def setMinimum(self, val):
        self._progress.setMainimum(val)

    def setValue(self, val):
        self._progress.setValue(val)

    def maximum(self):
        return self._progress.maximum()

    def minimum(self):
        return self._progress.mainimum()

    def value(self):
        return self._progress.value()

    def message(self):
        return self._msg

    def showMessage(self, msg):
        self._msg = msg
        self._progress.setFormat("    " + str(msg) + " %p%")

    def update(self):
        self._qss.update()
        self.processEvents()

    def finish(self, qwid):
        self._qss.finish(qwid)

    def processEvents(self):
        qapp = QApplication.instance()
        if qapp is not None:
            qapp.processEvents()


class TaggedLineEdit(QLineEdit):

    def __init__(self):
        QLineEdit.__init__(self)
        self.textcolor = QtGui.QColor(67, 172, 232)
        self.boxcolor = QtGui.QColor(175, 210, 255)
        self.setReadOnly(True)

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        surface_window = painter.window()
        font = self.font()
        font.setBold(True)
        # pal = self.palette()
        opt = QtGui.QStyleOptionFrame()
        style = self.style()

        opt.init(self)
        painter.setFont(font)
        style.drawPrimitive(
            QtGui.QStyle.PE_FrameLineEdit,
            opt,
            painter,
            self)

        painter.setClipRect(surface_window)
        painter.setPen(QtCore.Qt.NoPen)
        painter.drawRect(surface_window)

        painter.setPen(self.textcolor)
        painter.setBrush(self.boxcolor)
        fm = painter.fontMetrics()

        spacing = fm.width(' ')
        xoff = spacing
        for element in str(self.text()).split(','):
            if not element.strip():
                continue
            etxt = "+"+element
            w = fm.width(etxt)+2*spacing
            rect = QtCore.QRectF(xoff, 3, w, surface_window.height()-6)
            painter.drawRect(rect)
            painter.drawText(rect,
                             QtCore.Qt.AlignCenter |
                             QtCore.Qt.AlignVCenter,
                             etxt)
            xoff += w+3*spacing


class CCBStyledItemDelegate (QStyledItemDelegate):

    def paint(self, painter, options, index):
        newopts = QtGui.QStyleOptionViewItem(options)
        # Disabling decoration for selected items
        # and for items under mouse cursor
        newopts.showDecorationSelected = False
        newopts.state &= ~QtGui.QStyle.State_HasFocus
        newopts.state &= ~QtGui.QStyle.State_MouseOver
        # proced with object drawing
        QtGui.QStyledItemDelegate.paint(self, painter, newopts, index)


class ComboCheckBox(QComboBox):

    itemChanged = QtCore.pyqtSignal(QtGui.QStandardItem)
    checkStateChanged = QtCore.pyqtSignal()

    def __init__(self, *arg, **args):
        QComboBox.__init__(self, *arg, **args)
        model = QtGui.QStandardItemModel(0, 1)
        self.setModel(model)
        self.setItemDelegate(CCBStyledItemDelegate(self))
        self.setMinimumHeight(30)
        self.setLineEdit(TaggedLineEdit())
        self.setEditable(True)
        self.setInsertPolicy(QtGui.QComboBox.NoInsert)
        self.setEditText("")

        self.setSizePolicy(
            QtGui.QSizePolicy(QtGui.QSizePolicy.Minimum,
                              QtGui.QSizePolicy.Minimum))

        model.itemChanged.connect(self.itemChanged.emit)
        model.itemChanged.connect(self._emitCheckStateChanged)
        self.checkStateChanged.connect(self._updateEditText)
        self.editTextChanged.connect(self._test)

    def _test(self, txt):
        self._updateEditText()

    def _updateEditText(self):
        txt = ""
        model = self.model()
        total = model.rowCount()*model.columnCount()
        count = 0
        for row in range(model.rowCount()):
            for col in range(model.columnCount()):
                item = model.item(row, col)
                if item.checkState():
                    count += 1
                    txt += item.text() + ", "
        if count == total:
            txt = tr.tr('All')
        elif not txt:
            txt = tr.tr('None')
        self.setEditText(txt)

    def addItem(self, *arg, **args):
        """
            arg:
                see QtGui.QStandardItem for

            args:
                checked (bool)
        """
        item = QtGui.QStandardItem(*arg)

        item.setFlags(QtCore.Qt.ItemIsUserCheckable | QtCore.Qt.ItemIsEnabled)
        item.setData(QtCore.Qt.Unchecked, QtCore.Qt.CheckStateRole)

        if "checked" in args and args["checked"]:
            item.setCheckState(2)
        else:
            item.setCheckState(0)

        self.model().appendRow(item)
        self._updateEditText()
        return item

    def addItems(self, strlist):
        for txt in strlist:
            self.addItem(txt)

    def _emitCheckStateChanged(self):
        self.checkStateChanged.emit()


class ToolComboBox(Qt.QFrame):

    _selector = QComboBox

    def __init__(self, title="", tooltip="", useframe=True):

        Qt.QFrame.__init__(self)

        self.setFrameStyle(Qt.QFrame.Plain)
        self.setToolTip(tooltip)
        self._label = Qt.QLabel(title)
        self._selector = self._selector()

        vLayout = Qt.QHBoxLayout(self)
        vLayout.addWidget(self._label)
        vLayout.addWidget(self._selector)

        self.setLabel = self._label.setText
        self.addItem = self._selector.addItem
        self.addItems = self._selector.addItems
        self.count = self._selector.count
        self.currentIndexChanged = self._selector.currentIndexChanged
        self.currentIndex = self._selector.currentIndex
        self.setCurrentIndex = self._selector.setCurrentIndex
        self.currentText = self._selector.currentText
        self.duplicatesEnabled = self._selector.duplicatesEnabled
        self.setFrame = self._selector.setFrame
        self.hasFrame = self._selector.hasFrame
        self.clear = self._selector.clear

        self.setFrame(useframe)


class ToolComboCheckBox(ToolComboBox):

    _selector = ComboCheckBox

    def __init__(self, title="", tooltip="", useframe=True):
        ToolComboBox.__init__(self, title, tooltip, useframe)
        self._selector.setMinimumWidth(200)

        self.itemChanged = self._selector.itemChanged


class MagDoubleValidator(QtGui.QDoubleValidator):

    def validate(self, inp, pos):
        try:
            float(inp)
            return QtGui.QDoubleValidator.validate(self, inp, pos)
        except:
            ss = str(inp).strip()
            if ss == '':
                state = self.Acceptable
            else:
                state = self.Invalid
        else:
            state = self.Acceptable
        return (state, pos)


class MagItemDelegate(QStyledItemDelegate):

    def createEditor(self, parent, option, index):
        lineEdit = QLineEdit(parent)
        validator = MagDoubleValidator(-99, 99, 4, lineEdit)
        validator.setNotation(0)
        lineEdit.setValidator(validator)
        return lineEdit


class BandItemDelegate(QStyledItemDelegate):

    def createEditor(self, parent, option, index):
        comboBox = QComboBox(parent)
        comboBox.setEditable(False)
        for band in lcurves.COMPONENTS_NAME:
            comboBox.addItem(band)
        return comboBox

    def setEditorData(self, editor, index):

        value = str(index.model().data(index).toString())
        index = editor.findText(value)
        editor.setCurrentIndex(index)


class DialogBox(QDialog):

    def __init__(self, title="Dialog", buttons=QDialogButtonBox.Ok):
        QDialog.__init__(self)

        bbox = QDialogButtonBox(self)
        bbox.addButton(buttons)
        bbox.accepted.connect(self.accept)

        mainlayout = QVBoxLayout()
        self.central_layout = QVBoxLayout()

        mainlayout.addLayout(self.central_layout)
        mainlayout.addWidget(bbox)
        self.setLayout(mainlayout)

    def addWidget(self, wid):
        self.central_layout.addWidget(wid)


class ComponentMappingDialog(DialogBox):

    def __init__(self):
        DialogBox.__init__(self, tr.tr("Channel mapping dialog"))
        self._table = QTableWidget(0, 2)
        self._table.setItemDelegateForColumn(1, BandItemDelegate())

        self.addWidget(self._table)

    def exec_(self, channel_mapping):
        self._table.clear()
        self._table.setSortingEnabled(False)
        self._table.setHorizontalHeaderLabels(
            (tr.tr("Color Channel"), tr.tr("Assigned Band")))
        self._table.horizontalHeader().setResizeMode(
                1,
                QtGui.QHeaderView.Stretch)
        self._table.verticalHeader().hide()
        self._table.setRowCount(0)
        print("((", channel_mapping)
        for com in channel_mapping:
            channel_name = tr.tr("channel {0:03d}").format(com)
            band_name = str(channel_mapping[com])
            key_item = QTableWidgetItem(channel_name)
            val_item = QTableWidgetItem(band_name)

            key_item.setFlags(
                QtCore.Qt.ItemIsSelectable | QtCore.Qt.ItemIsEnabled)

            self._table.insertRow(0)
            self._table.setItem(0, 0, key_item)
            self._table.setItem(0, 1, val_item)

        self._table.setSortingEnabled(True)
        QtGui.QDialog.exec_(self)

        for i in range(self._table.rowCount()):
            key_item = self._table.item(i, 0)
            val_item = self._table.item(i, 1)

            ch = int(str(key_item.text())[-3:])
            band = str(val_item.text())
            channel_mapping[ch] = band
        print("[[", channel_mapping)
        return channel_mapping

    def show(self, channel_mapping):
        self.exec_(channel_mapping)


class PhotometricPropertiesDialog(DialogBox):

    def __init__(self):
        DialogBox.__init__(self, tr.tr("Unknown star"))
        self._table = QTableWidget(0, 2)
        self._table.setItemDelegateForColumn(1, MagItemDelegate())

        self.addWidget(self._table)

    def exec_(self, star, channel_mapping):
        self._table.clear()
        self._table.setSortingEnabled(False)
        self._table.setHorizontalHeaderLabels(
            (tr.tr("Asigned Band"), tr.tr("Magnitude")))
        self._table.horizontalHeader().setResizeMode(
                1,
                QtGui.QHeaderView.Stretch)
        self._table.verticalHeader().hide()
        self._table.setRowCount(0)

        mag_dict = star.magnitude.copy()
        print(mag_dict)
        for com in channel_mapping:
            band = str(channel_mapping[com])

            try:
                mag = str(star.magnitude[band])
            except KeyError:
                mag = ""

            key_item = QtGui.QTableWidgetItem(band)
            key_item.setFlags(
                QtCore.Qt.ItemIsSelectable | QtCore.Qt.ItemIsEnabled)
            val_item = QtGui.QTableWidgetItem(mag)

            self._table.insertRow(0)
            self._table.setItem(0, 0, key_item)
            self._table.setItem(0, 1, val_item)

        QtGui.QDialog.exec_(self)

        for i in range(self._table.rowCount()):
            key_item = self._table.item(i, 0)
            val_item = self._table.item(i, 1)
            band = str(key_item.text())
            try:
                mag_dict[band] = float(val_item.text())
            except ValueError:
                try:
                    mag_dict.pop(band)
                except KeyError:
                    continue

        return mag_dict

    def show(self, star, channel_mapping):
        return self.exec_(star, channel_mapping)


class ExifViewer(QDialog):

    def __init__(self, title=""):

        QDialog.__init__(self)

        self.setWindowTitle(title)
        self._table = QtGui.QTableWidget(0, 2)

        mainlayout = QtGui.QVBoxLayout()
        mainlayout.addWidget(self._table)

        self.setLayout(mainlayout)

    def showImageProperties(self, p):
        self._table.clear()
        self._table.setSortingEnabled(False)
        self._table.setHorizontalHeaderLabels(
            ("Key", "Value"))
        self._table.horizontalHeader().setResizeMode(
                1,
                QtGui.QHeaderView.Stretch)
        self._table.verticalHeader().hide()

        for key in p.keys():

            if key == 'listItem':
                continue
            key_item = QtGui.QTableWidgetItem(str(key))
            val_item = QtGui.QTableWidgetItem(str(p[key]))

            self._table.insertRow(0)
            self._table.setItem(0, 0, key_item)
            self._table.setItem(0, 1, val_item)

        self._table.setSortingEnabled(True)


class ImageViewer(QWidget):

    # titleChanged = QtCore.pyqtSignal(str)

    def __init__(self, infolabel=None):

        QWidget.__init__(self)

        self.zoom = 1
        self.min_zoom = 0
        self.actual_zoom = 1
        self.exposure = 0
        self.zoom_enabled = False
        self.zoom_fit = False
        self.mapped_image = mappedimage.MappedImage(name='image')
        self.fit_levels = False
        self.panning = False
        self.feature_moveing = False
        self.selected_feature = None
        self.colorbarmap = mappedimage.MappedImage(name='colorbar')
        self.user_cursor = QtCore.Qt.OpenHandCursor
        self.levels_range = [0, 100]
        self.image_name = ""
        self.image_features = []
        self.image_properties = {}
        self.statusLabelMousePos = infolabel

        toolbar = Qt.QToolBar('ImageViewerToolBar')

        # ToolBar actions
        save_action = QtGui.QAction(
            utils.getQIcon("save-image"),
            tr.tr('Save the displayed image to a file'),
            self)

        action_edit_levels = QtGui.QAction(
            utils.getQIcon("edit-levels"),
            tr.tr('Edit input levels'),
            self)

        action_edit_levels.setCheckable(True)

        action_show_exif = QtGui.QAction(
            utils.getQIcon("show-exif"),
            tr.tr('Show image properties'),
            self)

        # colormap controls
        self.colormap_selector = ToolComboBox(
            tr.tr("colormap:"),
            tooltip=tr.tr("Image color-map"))

        data = np.meshgrid(np.arange(64), np.arange(64))[0]

        keys = cmaps.COLORMAPS.keys()
        keys.sort()

        for ccmap in keys:
            cmap = cmaps.COLORMAPS[ccmap]
            icon = Qt.QPixmap.fromImage(
                mappedimage.arrayToQImage(data, cmap=cmap, fit_levels=True))
            self.colormap_selector.addItem(QtGui.QIcon(icon), cmap.name)

        self.colormap_selector.setEnabled(True)

        # zoom controls
        self.zoomCheckBox = QtGui.QCheckBox(tr.tr("zoom: none"))
        self.zoomSlider = QtGui.QSlider(QtCore.Qt.Horizontal)
        self.zoomDoubleSpinBox = QtGui.QDoubleSpinBox()

        # image viewer controls
        self.imageLabel = QtGui.QLabel()
        self.scrollArea = QtGui.QScrollArea()
        self.viewHScrollBar = self.scrollArea.horizontalScrollBar()
        self.viewVScrollBar = self.scrollArea.verticalScrollBar()

        # colorbar controls
        self.colorBar = QtGui.QLabel()
        self.fitMinMaxCheckBox = QtGui.QCheckBox(tr.tr("contrast: none"))
        self.minLevelDoubleSpinBox = QtGui.QDoubleSpinBox()
        self.maxLevelDoubleSpinBox = QtGui.QDoubleSpinBox()

        self.colorBar.current_val = None
        self.colorBar.max_val = 1.0
        self.colorBar.min_val = 0.0
        self.colorBar._is_rgb = False

        self.zoomSlider.setMinimum(0)
        self.zoomSlider.setMaximum(1000)
        self.zoomSlider.setSingleStep(1)

        self.zoomDoubleSpinBox.setDecimals(3)
        self.zoomDoubleSpinBox.setMinimum(0.01)
        self.zoomDoubleSpinBox.setMaximum(10.0)
        self.zoomSlider.setSingleStep(0.05)

        self.imageLabel.setMouseTracking(True)

        self.scrollArea.setMouseTracking(False)
        self.scrollArea.setFrameShape(QtGui.QFrame.StyledPanel)
        self.scrollArea.setFrameShadow(QtGui.QFrame.Sunken)
        self.scrollArea.setLineWidth(1)
        self.scrollArea.setWidgetResizable(True)
        self.scrollArea.setWidget(self.imageLabel)
        self.scrollArea.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop)
        self.scrollArea.setFrameShape(QtGui.QFrame.StyledPanel)
        self.scrollArea.setFrameShadow(QtGui.QFrame.Sunken)

        self.scrollArea.setVerticalScrollBarPolicy(
            QtCore.Qt.ScrollBarAsNeeded)

        self.scrollArea.setHorizontalScrollBarPolicy(
            QtCore.Qt.ScrollBarAsNeeded)

        self.scrollArea.setSizePolicy(
            QtGui.QSizePolicy(QtGui.QSizePolicy.Expanding,
                              QtGui.QSizePolicy.Expanding))

        self.colorBar.setSizePolicy(
            QtGui.QSizePolicy(QtGui.QSizePolicy.Expanding,
                              QtGui.QSizePolicy.Fixed))

        self.colorBar.setMinimumSize(QtCore.QSize(0, 25))
        self.colorBar.setFrameShape(QtGui.QFrame.StyledPanel)
        self.colorBar.setFrameShadow(QtGui.QFrame.Sunken)

        self.fitMinMaxCheckBox.setTristate(True)

        self.minLevelDoubleSpinBox.setMinimum(0.0)
        self.minLevelDoubleSpinBox.setMaximum(100.0)

        self.maxLevelDoubleSpinBox.setMinimum(0.0)
        self.maxLevelDoubleSpinBox.setMaximum(100.0)

        mainlayout = QtGui.QVBoxLayout()
        self.viewlayout = QtGui.QHBoxLayout()
        cbarlayout = QtGui.QHBoxLayout()

        self.setLayout(mainlayout)

        cbarlayout.addWidget(self.fitMinMaxCheckBox)
        cbarlayout.addWidget(self.minLevelDoubleSpinBox)
        cbarlayout.addWidget(self.colorBar)
        cbarlayout.addWidget(self.maxLevelDoubleSpinBox)

        toolbar.addAction(save_action)
        toolbar.addAction(action_edit_levels)
        toolbar.addAction(action_show_exif)
        toolbar.addWidget(self.colormap_selector)
        toolbar.addWidget(self.zoomCheckBox)
        toolbar.addWidget(self.zoomSlider)
        toolbar.addWidget(self.zoomDoubleSpinBox)

        self.viewlayout.addWidget(self.scrollArea)
        self.viewlayout.addWidget(self.mapped_image.getLevelsDialog())
        self.mapped_image.getLevelsDialog().hide()

        mainlayout.addWidget(toolbar)
        mainlayout.addLayout(self.viewlayout)
        mainlayout.addLayout(cbarlayout)

        # mousemove callback
        self.imageLabel.mouseMoveEvent = self.imageLabelMouseMoveEvent
        self.imageLabel.mousePressEvent = self.imageLabelMousePressEvent
        self.imageLabel.mouseReleaseEvent = self.imageLabelMouseReleaseEvent

        # mouse wheel scroll callback
        self.scrollArea.wheelEvent = self.scrollAreaWheelEvent

        # resize callback
        self.scrollArea.resizeEvent = self.scrollAreaResizeEvent

        # paint callback
        self.imageLabel.paintEvent = self.imageLabelPaintEvent

        # paint callback for colorBar
        self.colorBar.paintEvent = self.colorBarPaintEvent

        save_action.triggered.connect(self.doSaveImage)
        action_edit_levels.triggered.connect(self.doEditLevels)
        action_show_exif.triggered.connect(self.showImageProperties)

        self.mapped_image.remapped.connect(self.updateImage)
        self.zoomCheckBox.stateChanged.connect(self.setZoomMode)
        self.zoomSlider.valueChanged.connect(self.signalSliderZoom)
        self.zoomDoubleSpinBox.valueChanged.connect(self.signalSpinZoom)
        self.fitMinMaxCheckBox.stateChanged.connect(self.setLevelsFitMode)
        self.minLevelDoubleSpinBox.valueChanged.connect(self.setMinLevel)
        self.maxLevelDoubleSpinBox.valueChanged.connect(self.setMaxLevel)
        self.colormap_selector.currentIndexChanged.connect(self.setColorMapID)

        self.setZoomMode(1, True)
        self.setOutputLevelsRange((0, 100))
        self.setLevelsFitMode(0)

    def setFeatures(self, flist):
        self.image_features = flist
        self.imageLabel.update()

    def doSaveImage(self):
        if self.mapped_image is not None:
            frm = utils.Frame()
            frm.saveData(data=self.mapped_image.getMappedData())

    def showImageProperties(self):
        ev = ExifViewer(self.image_name+" "+tr.tr("properties"))
        ev.showImageProperties(self.image_properties)
        ev.exec_()

    def setColorMapID(self, cmapid):
        self.setColorMap(cmaps.COLORMAPS[cmapid])

    def setColorMap(self, cmap):
        log.log(repr(self), "Setting new colormap", level=logging.DEBUG)
        if self.mapped_image is not None:
            self.mapped_image.setColormap(cmap, update=False)
            self.generateScaleMaps(remap=False)
            self.mapped_image.remap()

    def getColorMap(self):
        return self.mapped_image.getColormap()

    def updateColorMap(self, val):
        self.colormap_selector.setCurrentIndex(val)

    def generateScaleMaps(self, remap=True):

        if self.mapped_image is None:
            return

        ncomponents = self.mapped_image.componentsCount()

        if ncomponents < 1:
            return

        elif ncomponents == 1:
            log.log(repr(self),
                    "Generating ColorBar scalemaps...",
                    level=logging.DEBUG)
            h_mul = int(self.colorBar.height()-8)
            data1 = np.arange(0, self.colorBar.width())
            data1 = data1*255.0 / self.colorBar.width()
            data2 = np.array([data1]*h_mul)
            data3 = data2

        else:
            log.log(repr(self),
                    "Generating ColorBar RGB scalemaps...",
                    level=logging.DEBUG)
            h_mul = int((self.colorBar.height()-8) / float(ncomponents))
            data1 = np.arange(0, self.colorBar.width())
            data1 = data1*255.0 / self.colorBar.width()
            data2 = np.array([data1]*h_mul)
            hh = len(data2)
            data3 = np.zeros((ncomponents*hh, len(data1), ncomponents))

            for i in range(ncomponents):
                data3[i*hh:(i+1)*hh, 0:, i] = data2

        if isinstance(self.colorbarmap, mappedimage.MappedImage):
            self.colorbarmap.setColormap(self.mapped_image.getColormap(),
                                         update=False)
            self.colorbarmap.setOutputLevels(lrange=self.levels_range,
                                             lfitting=self.fit_levels,
                                             update=False)
            self.colorbarmap.setData(data3, update=remap)
        else:
            self.colorbarmap = mappedimage.MappedImage(
                data3,
                self.mapped_image.getColormap(),
                fit_levels=self.fit_levels,
                levels_range=self.levels_range,
                name='colorbar',
                update=remap)

    # resizeEvent callback
    def scrollAreaResizeEvent(self, event):
        if self.zoom_fit:
            self.updateImage()
        self.generateScaleMaps()
        return QtGui.QScrollArea.resizeEvent(self.scrollArea, event)

    # mouseMoveEvent callback
    def imageLabelMouseMoveEvent(self, event):
        mx = event.x()
        my = event.y()
        x = utils.Int(mx/self.actual_zoom)
        y = utils.Int(my/self.actual_zoom)

        if (self.mapped_image is not None):
            if self.mapped_image.getOriginalData() is not None:
                imshape = self.mapped_image.getOriginalData().shape
                ymax = imshape[0]
                xmax = imshape[1]
                if ((y >= 0) and (y < ymax) and (x >= 0) and (x < xmax)):
                    # the mouse cursor is over the image area
                    pix_val = self.mapped_image.getOriginalData()[y, x]
                    self.current_pixel = (x, y)
                    try:
                        self.colorBar.current_val = tuple(pix_val)
                    except:
                        try:
                            self.colorBar.current_val = (int(pix_val),)
                        except:
                            comp_count = self.mapped_image.componentsCount()
                            self.colorBar.current_val = (0,)*comp_count
                    self.colorBar.update()
            else:
                pix_val = None

        if self.panning:
            sx = mx-self.movement_start[0]
            sy = my-self.movement_start[1]

            self.viewHScrollBar.setValue(self.viewHScrollBar.value()-sx)
            self.viewVScrollBar.setValue(self.viewVScrollBar.value()-sy)

        elif self.feature_moveing:
            self.selected_feature.move(x, y)
            self.update()
            self.imageLabel.repaint()
        else:
            for feature in self.image_features:
                if ((x-feature.x)**2 + (y-feature.y)**2) < feature.r**2:
                    self.scrollArea.setCursor(QtCore.Qt.SizeAllCursor)
                    self.imageLabel.setCursor(QtCore.Qt.SizeAllCursor)
                    feature.mouse_over = True
                    self.selected_feature = feature
                    break
                else:
                    self.imageLabel.setCursor(self.user_cursor)
                    feature.mouse_over = False
                    self.selected_feature = None
            self.update()
            self.imageLabel.repaint()
        return QtGui.QLabel.mouseMoveEvent(self.imageLabel, event)

    def scrollAreaWheelEvent(self, event):
        if self.zoom_enabled:
            delta = np.sign(event.delta())*math.log10(self.zoom+1)/2.5
            mx = event.x()
            my = event.y()
            cx = self.scrollArea.width()/2.0
            cy = self.scrollArea.height()/2.0
            sx = (cx - mx)/2
            sy = (cy - my)/2
            self.viewHScrollBar.setValue(self.viewHScrollBar.value()-sx)
            self.viewVScrollBar.setValue(self.viewVScrollBar.value()-sy)

            self.setZoom(self.zoom+delta)

        return Qt.QWheelEvent.accept(event)

    def imageLabelMousePressEvent(self, event):

        btn = event.button()
        if btn == 1:
            self.movement_start = (event.x(), event.y())
            if self.selected_feature is None:
                self.scrollArea.setCursor(QtCore.Qt.ClosedHandCursor)
                self.imageLabel.setCursor(QtCore.Qt.ClosedHandCursor)
                self.panning = True
                self.feature_moveing = False
            else:
                self.panning = False
                self.scrollArea.setCursor(QtCore.Qt.BlankCursor)
                self.imageLabel.setCursor(QtCore.Qt.BlankCursor)
                self.feature_moveing = True
                self.selected_feature.mouse_grabbed = True

        return QtGui.QLabel.mousePressEvent(self.imageLabel, event)

    def imageLabelMouseReleaseEvent(self, event):

        btn = event.button()
        if btn == 1:
            self.panning = False
            self.feature_moveing = False
            self.scrollArea.setCursor(self.user_cursor)
            self.imageLabel.setCursor(self.user_cursor)

            if not (self.selected_feature is None):
                self.selected_feature.mouse_grabbed = False

        return QtGui.QLabel.mouseReleaseEvent(self.imageLabel, event)

    # paintEvent callback for imageLabel
    def imageLabelPaintEvent(self, obj):

        painter = Qt.QPainter(self.imageLabel)

        if self.mapped_image is not None:
            qimg = self.mapped_image.getQImage()
            if qimg is not None:
                painter.scale(self.actual_zoom, self.actual_zoom)
                painter.drawImage(0, 0, self.mapped_image.getQImage())

        for feature in self.image_features:
            feature.draw(painter)

        del painter
        return QtGui.QLabel.paintEvent(self.imageLabel, obj)

    # paintEvent callback for colorBar
    def colorBarPaintEvent(self, obj):

        cb = self.colorBar
        if self.mapped_image is None:
            return QtGui.QLabel.paintEvent(cb, obj)

        if self.colorBar.current_val is not None:
            painter = Qt.QPainter(self.colorBar)

            _gpo = 2  # geometric corrections
            _gno = 5  # geometric corrections
            _gpv = 4  # geometric corrections

            dw = painter.device().width() - _gno
            dh = painter.device().height() - _gpv*2

            devicerect = QtCore.QRect(_gpo, _gpv, dw, dh)

            fnt_size = 10
            painter.setFont(Qt.QFont("Arial", fnt_size))
            y = (cb.height() + fnt_size/2)/2 + 2
            max_txt = str(cb.max_val)
            txt_x = cb.width() - (fnt_size-2)*len(max_txt)
            txt_y = y

            if self.statusLabelMousePos is not None:
                try:
                    self.statusLabelMousePos.setText(
                        'position=' + str(self.current_pixel) +
                        ' value=' + str(cb.current_val))
                except:
                    pass

            qimg = self.colorbarmap.getQImage()
            if qimg is not None:
                painter.drawImage(devicerect, qimg)

            ncomp = len(cb.current_val)
            hh = dh/ncomp

            painter.setCompositionMode(22)

            for i in range(ncomp):
                try:
                    v1 = float(cb.current_val[i]-cb.min_val)
                    v2 = float(cb.max_val-cb.min_val)
                    x = int((v1/v2) * (cb.width()-_gno)) + _gpo
                except Exception:
                    x = -1
                painter.setPen(QtCore.Qt.white)
                painter.drawLine(x, _gpv + i*hh, x, _gpv + (i+1)*hh)

            painter.setCompositionMode(0)
            painter.setPen(QtCore.Qt.white)
            painter.drawText(fnt_size-4, y, str(cb.min_val))
            painter.setPen(QtCore.Qt.black)
            painter.drawText(txt_x, txt_y, max_txt)

            del painter

        return QtGui.QLabel.paintEvent(cb, obj)

    def setZoomMode(self, val, check=False):

        if check:
            self.zoomCheckBox.setCheckState(val)

        if val is 0:
            self.zoomCheckBox.setText(tr.tr('zoom: none'))
            self.zoomSlider.setEnabled(False)
            self.zoomDoubleSpinBox.setEnabled(False)
            self.zoom_enabled = False
            self.zoom_fit = False
        elif val is 1:
            self.zoomCheckBox.setText(tr.tr('zoom: fit'))
            self.zoomSlider.setEnabled(False)
            self.zoomDoubleSpinBox.setEnabled(False)
            self.zoom_enabled = False
            self.zoom_fit = True
        else:
            self.zoomCheckBox.setText(tr.tr('zoom: full'))
            self.zoomSlider.setEnabled(True)
            self.zoomDoubleSpinBox.setEnabled(True)
            self.zoom_enabled = True
            self.zoom_fit = False
        self.updateImage()

    def setZoom(self, zoom):

        if zoom <= self.zoomDoubleSpinBox.maximum():
            self.zoom = zoom
        else:
            self.zoom = self.zoomDoubleSpinBox.maximum()

        self.zoomDoubleSpinBox.setValue(self.zoom)
        self.zoomSlider.setValue(utils.Int(self.zoom*100))

    def signalSliderZoom(self, value, update=False):
        self.zoom = value/100.0
        vp = self.getViewport()
        self.zoomDoubleSpinBox.setValue(self.zoom)
        if update:
            self.updateImage()

        self.setViewport(vp)

    def signalSpinZoom(self, value, update=True):
        self.zoom = value
        vp = self.getViewport()
        self.zoomSlider.setValue(utils.Int(self.zoom*100))
        if update:
            self.updateImage()
        self.setViewport(vp)

    def getViewport(self):
        try:
            hs_val = float(self.viewHScrollBar.value())
            hs_max = float(self.viewHScrollBar.maximum())
            x = hs_val/hs_max
        except ZeroDivisionError:
            x = 0.5
        try:
            vs_val = float(self.viewVScrollBar.value())
            vs_max = float(self.viewVScrollBar.maximum())
            y = vs_val/vs_max
        except ZeroDivisionError:
            y = 0.5

        return (x, y)

    def setViewport(self, viewPoint):
        hs_max = self.viewHScrollBar.maximum()
        vs_max = self.viewVScrollBar.maximum()
        self.viewHScrollBar.setValue(viewPoint[0]*hs_max)
        self.viewVScrollBar.setValue(viewPoint[1]*vs_max)

    def showImage(self, image):
        if isinstance(image, mappedimage.MappedImage):
            log.log(repr(self),
                    "Displaying new mappedimage",
                    level=logging.DEBUG)
            del self.mapped_image
            self.mapped_image.remapped.disconnect(self.updateImage)
            self.mapped_image.mappingChanged.disconnect(self.updateImage)
            self.viewlayout.removeWidget(self.mapped_image.getLevelsDialog())
            self.mapped_image = image
            self.viewlayout.addWidget(self.mapped_image.getLevelsDialog())
            self.mapped_image.getLevelsDialog().hide()
            self.mapped_image.mappingChanged.disconnect(self.updateImage)
            self.mapped_image.remapped.connect(self.updateImage)
            self.updateImage()
        else:
            log.log(repr(self),
                    "Displaying new image",
                    level=logging.DEBUG)
            self.mapped_image.setData(image)

    def clearImage(self):
        self.mapped_image.setData(None)
        self.imageLabel.setPixmap(Qt.QPixmap())

    def updateImage(self, paint=True, overridden_image=None):

        log.log(repr(self),
                "Updating the displayed image",
                level=logging.DEBUG)

        if overridden_image is not None:
            if isinstance(overridden_image, mappedimage.MappedImage):
                current_image = overridden_image
            else:
                return False
        elif self.mapped_image is not None:
            current_image = self.mapped_image
        else:
            return False

        qimg = current_image.getQImage()
        if qimg is None:
            return False

        imh = qimg.height()
        imw = qimg.width()
        if imw*imh <= 0:
            return False

        self.colorbarmap.setCurve(
            *current_image.getCurve(),
            update=False)

        self.colorbarmap.setMWBCorrectionFactors(
            *current_image.getMWBCorrectionFactors(),
            update=False)

        self.colorbarmap.setOutputLevels(
            lrange=self.levels_range,
            lfitting=self.fit_levels,
            update=False)

        self.colorbarmap.setMapping(
            *current_image.getMapping(),
            update=False)

        colormap_comp_count = self.colorbarmap.getNumberOfComponents()
        curr_image_comp_count = current_image.getNumberOfComponents()
        components_match = colormap_comp_count == curr_image_comp_count

        if (self.colorbarmap.getQImage() is None or not components_match):
            self.generateScaleMaps()
        else:
            self.colorbarmap.remap()

        try:
            pix_x = self.current_pixel[0]
            pix_y = self.current_pixel[1]
            pix_val = current_image.getOriginalData()[pix_y, pix_x]
            try:
                self.colorBar.current_val = tuple(pix_val)
            except:
                try:
                    self.colorBar.current_val = (int(pix_val),)
                except:
                    self.colorBar.current_val = (0,)*curr_image_comp_count
            self.colorBar.update()
        except Exception:
            self.current_pixel = (0, 0)

        if self.zoom_enabled:
            self.actual_zoom = self.zoom
        elif self.zoom_fit:
            self.actual_zoom = min(float(self.scrollArea.width()-10)/imw,
                                   float(self.scrollArea.height()-10)/imh)
            self.zoomDoubleSpinBox.setValue(self.zoom)
        else:
            self.actual_zoom = 1

        if paint:
            imh += 1
            imw += 1
            self.imageLabel.setMaximumSize(imw*self.actual_zoom,
                                           imh*self.actual_zoom)
            self.imageLabel.setMinimumSize(imw*self.actual_zoom,
                                           imh*self.actual_zoom)
            self.imageLabel.resize(imw*self.actual_zoom,
                                   imh*self.actual_zoom)
            self.imageLabel.update()

            if current_image._original_data is not None:
                self.colorBar.max_val = current_image._original_data.max()
                self.colorBar.min_val = current_image._original_data.min()

                if (self.colorBar.max_val <= 1) or self.fit_levels:
                    pass
                elif self.colorBar.max_val <= 255:
                    self.colorBar.max_val *= 255.0/self.colorBar.max_val
                elif self.colorBar.max_val <= 65536:
                    self.colorBar.max_val *= 65536.0/self.colorBar.max_val

                if self.fit_levels:
                    pass
                elif self.colorBar.min_val > 0:
                    self.colorBar.min_val *= 0

                if not self.colorBar.isVisible():
                    self.colorBar.show()
            else:
                self.colorBar.max_val = 1
                self.colorBar.max_val = 0
                if self.colorBar.isVisible():
                    self.colorBar.hide()

            # this shuold avoid division by zero
            if self.colorBar.max_val == self.colorBar.min_val:
                self.colorBar.max_val = self.colorBar.max_val+1
                self.colorBar.min_val = self.colorBar.min_val-1

        return True

    def setOutputLevelsRange(self, lrange):
        self.minLevelDoubleSpinBox.setValue(np.min(lrange))
        self.maxLevelDoubleSpinBox.setValue(np.max(lrange))

    def setMinLevel(self, val):
        self.levels_range[0] = val
        if val <= self.levels_range[1]-1:
            self.setLevelsFitMode(self.fit_levels)
        else:
            self.maxLevelDoubleSpinBox.setValue(val+1)

    def setMaxLevel(self, val):
        self.levels_range[1] = val
        if val >= self.levels_range[0]+1:
            self.setLevelsFitMode(self.fit_levels)
        else:
            self.minLevelDoubleSpinBox.setValue(val-1)

    def forceDisplayLevelsFitMode(self, state):
        self.setLevelsFitMode(state)
        self.fitMinMaxCheckBox.hide()

    def setLevelsFitMode(self, state):

        log.log(repr(self),
                "Updating output levels",
                level=logging.DEBUG)

        if state == 0:
            self.minLevelDoubleSpinBox.hide()
            self.maxLevelDoubleSpinBox.hide()
            self.fitMinMaxCheckBox.setText(tr.tr('contrast')+': ' +
                                           tr.tr('none'))
        elif state == 1:
            self.minLevelDoubleSpinBox.hide()
            self.maxLevelDoubleSpinBox.hide()
            self.fitMinMaxCheckBox.setText(tr.tr('contrast')+': ' +
                                           tr.tr('full'))
        else:
            self.minLevelDoubleSpinBox.show()
            self.maxLevelDoubleSpinBox.show()
            self.fitMinMaxCheckBox.setText(tr.tr('contrast')+': ' +
                                           tr.tr('yes'))
        self.fit_levels = state

        Qt.QApplication.instance().processEvents()

        if self.mapped_image is not None:
            self.setOutputLevelsRange(self.levels_range)
            self.mapped_image.setOutputLevels(self.levels_range,
                                              self.fit_levels,
                                              update=True)
            self.updateImage()
        else:
            self.generateScaleMaps()

        self.colorBar.update()

    def doEditLevels(self, clicked):
        return self.mapped_image.editLevels(clicked)


class DifferenceViewer(ImageViewer):

    def __init__(self, reference=None):

        ImageViewer.__init__(self)
        self.offset = (0, 0, 0)
        self.ref_shift = (0, 0, 0)
        self.reference_image = mappedimage.MappedImage(reference)

    def setOffset(self, dx, dy, theta):
        self.offset = (dx, dy, theta)
        log.log(repr(self),
                "Setting image offset to " + str(self.offset),
                level=logging.DEBUG)
        self.imageLabel.update()
        self.update()

    def setRefShift(self, dx, dy, theta):
        self.ref_shift = (dx, dy, theta)
        log.log(repr(self),
                "Setting reference image offset to " + str(self.ref_shift),
                level=logging.DEBUG)
        self.imageLabel.update()
        self.update()

    def setRefImage(self, image):
        if isinstance(image, mappedimage.MappedImage):
            del self.mapped_image
            self.reference_image = image
        else:
            self.reference_image.setData(image)
        self.updateImage()

    # paintEvent callback
    def imageLabelPaintEvent(self, obj):
        painter = Qt.QPainter(self.imageLabel)

        if ((self.mapped_image is not None) and
                (self.reference_image is not None)):
            # then we can draw the difference

            ref = self.reference_image.getQImage()
            img = self.mapped_image.getQImage()

            if (img is None) or (ref is None):
                return

            rot_center = (img.width()/2.0, img.height()/2.0)
            mainframe_angle = -self.ref_shift[2]

            painter.scale(self.actual_zoom, self.actual_zoom)
            painter.translate(rot_center[0], rot_center[1])
            painter.rotate(mainframe_angle)
            painter.drawImage(-int(rot_center[0]),
                              -int(rot_center[1]),
                              ref)
            painter.drawLine(rot_center[0], rot_center[1],
                             rot_center[0]+50, rot_center[1])
            painter.setCompositionMode(22)

            x = self.offset[0] - self.ref_shift[0]
            y = self.offset[1] - self.ref_shift[1]

            cosa = math.cos(np.deg2rad(-self.ref_shift[2]))
            sina = math.sin(np.deg2rad(-self.ref_shift[2]))

            xi = x*cosa + y*sina
            yi = y*cosa - x*sina

            painter.translate(-xi, -yi)
            painter.rotate(-self.offset[2]+self.ref_shift[2])

            painter.drawImage(-int(rot_center[0]),
                              -int(rot_center[1]),
                              img)
            painter.setCompositionMode(0)

            # drawing mainframe
            painter.resetTransform()
            painter.translate(15, 15)
            painter.rotate(mainframe_angle)

            # x axis
            painter.setPen(QtCore.Qt.red)
            painter.drawLine(0, 0, 50, 0)
            painter.drawLine(40, 3, 50, 0)
            painter.drawLine(40, -3, 50, 0)

            # y axis
            painter.setPen(QtCore.Qt.green)
            painter.drawLine(0, 0, 0, 50)
            painter.drawLine(-3, 40, 0, 50)
            painter.drawLine(3, 40, 0, 50)
        del painter


class DropDownWidget(QWidget):

    def __init__(self, parent=None):
        QWidget.__init__(self, parent)

    def paintEvent(self, event):
        opt = QtGui.QStyleOption()
        opt.init(self)
        painter = QtGui.QPainter(self)
        self.style().drawPrimitive(QtGui.QStyle.PE_Widget,
                                   opt,
                                   painter,
                                   self)


class PlotSubWidget(QWidget):

    def __init__(self, parent=None):
        assert isinstance(parent, PlotWidget), "parent is not a PlotWidget"
        QWidget.__init__(self, parent)
        gboxlayout = Qt.QGridLayout()
        titlelayout = Qt.QHBoxLayout()

        self._click_offset = QtCore.QPoint()
        self._padding = (10, 10)
        self.resize(150, 100)
        self._grip_size = 6
        self._gripes = {
            (0.0, 0.0): QtCore.Qt.SizeFDiagCursor,
            (0.5, 0.0): QtCore.Qt.SizeVerCursor,
            (1.0, 0.0): QtCore.Qt.SizeBDiagCursor,
            (0.0, 0.5): QtCore.Qt.SizeHorCursor,
            (1.0, 0.5): QtCore.Qt.SizeHorCursor,
            (0.0, 1.0): QtCore.Qt.SizeBDiagCursor,
            (0.5, 1.0): QtCore.Qt.SizeVerCursor,
            (1.0, 1.0): QtCore.Qt.SizeFDiagCursor
        }
        self._resizing = False
        self._tlt_lbl = QtGui.QLabel()
        self.close_button = QtGui.QPushButton('X')

        self._tlt_lbl.setAlignment(QtCore.Qt.AlignCenter)
        self._tlt_lbl.setObjectName("Title")
        self._tlt_lbl.setSizePolicy(
            QtGui.QSizePolicy(QtGui.QSizePolicy.Expanding,
                              QtGui.QSizePolicy.MinimumExpanding))

        self.close_button.setObjectName("Close")
        self.close_button.setCursor(QtCore.Qt.PointingHandCursor)

        self.close_button.setSizePolicy(
            QtGui.QSizePolicy(QtGui.QSizePolicy.Minimum,
                              QtGui.QSizePolicy.MinimumExpanding))

        self.setCursor(QtCore.Qt.SizeAllCursor)
        self.setMouseTracking(True)

        self.setFocusPolicy(QtCore.Qt.ClickFocus)

        self.setMinimumSize(100, 50)

        titlelayout.addWidget(self.close_button)
        titlelayout.addWidget(self._tlt_lbl)

        gboxlayout.setContentsMargins(self._grip_size, self._grip_size,
                                      self._grip_size, self._grip_size)
        gboxlayout.addLayout(titlelayout, 0, 0, 1, 2)

        self.setLayout(gboxlayout)
        self.setEnabled(True)
        self.close_button.clicked.connect(self.hide)

    def setWindowTitle(self, title):
        self._tlt_lbl.setText(str(title))

    def _mouseOverGrip(self, pos):
        x = pos.x()
        y = pos.y()

        for grip in self._gripes.keys():
            grip_x = (self.width()-self._grip_size)*grip[0]
            grip_y = (self.height()-self._grip_size)*grip[1]
            if (x > grip_x and y > grip_y and
                    x < grip_x + self._grip_size and
                    y < grip_y + self._grip_size):
                return self._gripes[grip]
        return False

    def mousePressEvent(self, event):
        self._click_offset = event.pos()
        # is cursor over a grip?
        self._resizing = self._mouseOverGrip(self._click_offset)

    def mouseReleaseEvent(self, event):
        self._resizing = False
        self.setCursor(QtCore.Qt.SizeAllCursor)

    def mouseMoveEvent(self, event):
        if not self.hasFocus():
            self.setCursor(QtCore.Qt.PointingHandCursor)
            return

        x = event.x()
        y = event.y()

        cx = self.width()/2
        cy = self.height()/2

        if self._resizing == QtCore.Qt.SizeVerCursor:
            self.setCursor(self._resizing)
            if y < cy:
                self.move(self.x(), self.mapToParent(event.pos()).y())
                self.resize(self.width(), self.height() - y)
            else:
                self.resize(self.width(), y)
        elif self._resizing == QtCore.Qt.SizeHorCursor:
            self.setCursor(self._resizing)
            if x < cx:
                self.move(self.mapToParent(event.pos()).x(), self.y())
                self.resize(self.width() - x, self.height())
            else:
                self.resize(x, self.height())
        elif self._resizing == QtCore.Qt.SizeBDiagCursor:
            self.setCursor(self._resizing)
            if x < cx:
                self.move(self.mapToParent(event.pos()).x(), self.y())
                self.resize(self.width() - x, y)
            else:
                self.move(self.x(), self.mapToParent(event.pos()).y())
                self.resize(x, self.height() - y)
        elif self._resizing == QtCore.Qt.SizeFDiagCursor:
            self.setCursor(self._resizing)
            if x < cx:
                self.move(self.mapToParent(event.pos()))
                self.resize(self.width() - x, self.height() - y)
            else:
                self.resize(x, y)
        else:
            cursor = self._mouseOverGrip(event.pos())
            if cursor:
                self.setCursor(cursor)
            else:
                self.setCursor(QtCore.Qt.SizeAllCursor)
            if event.buttons() & QtCore.Qt.LeftButton:
                self.move(self.mapToParent(event.pos() - self._click_offset))

    def render(self, painter):
        opt = QtGui.QStyleOption()
        opt.init(self)
        style = self.style()
        style.drawPrimitive(QtGui.QStyle.PE_Widget, opt, painter, self)

    def _paintGripes(self, painter):
        oldbrush = painter.brush()
        oldpen = painter.pen()
        painter.setPen(QtCore.Qt.gray)
        painter.setBrush(QtCore.Qt.green)
        for grip in self._gripes.keys():
            x = (self.width()-self._grip_size)*grip[0]
            y = (self.height()-self._grip_size)*grip[1]
            painter.drawRect(x, y, self._grip_size, self._grip_size)
        painter.setBrush(oldbrush)
        painter.setPen(oldpen)
        pass

    def paintEvent(self, event):
        painter = Qt.QPainter(self)
        painter.setRenderHint(painter.Antialiasing)
        surface_window = painter.window()

        w = surface_window.width()
        h = surface_window.height()
        f = painter.font()

        rect1 = QtCore.QRectF(0, 0, w, h)
        rect2 = QtCore.QRectF(self._padding[0],
                              self._padding[1],
                              w - 2*self._padding[0],
                              h - 2*self._padding[1])

        painter.setPen(QtCore.Qt.black)
        painter.setBrush(QtCore.Qt.white)
        painter.drawRect(rect1)

        f.setBold(True)
        painter.setFont(f)
        painter.drawText(rect2,
                         QtCore.Qt.AlignHCenter |
                         QtCore.Qt.AlignTop,
                         self.windowTitle())
        f.setBold(False)
        painter.setFont(f)

        self.render(painter)
        if self.hasFocus():
            self._paintGripes(painter)


class PlotLegendWidget(PlotSubWidget):

    def __init__(self, parent=None):
        PlotSubWidget.__init__(self, parent)
        self.setWindowTitle(tr.tr("Legend"))
        self.setStyleSheet(
            """
            QLabel#Title
            {
                background-color: none;
                font: bold;
            }
            """)
        self.close_button.hide()
        self.close_button.deleteLater()
        self.close_button.setParent(None)
        del self.close_button
        gboxlayout = self.layout()
        gboxlayout.setRowStretch(1, 1)

    def render(self, painter):
        if self.parent()._backend is None:
            count = 0
            y_off = painter.fontMetrics().lineSpacing()
            for plot in self.parent().plots:
                if plot.isVisible():
                    elx = self._padding[0]
                    ely = 3*self._padding[1] + y_off + 20*count
                    plot.drawQtLegendElement(painter, elx, ely)
                    count += 1


class PlotPropertyDialogWidget(PlotSubWidget):

    def __init__(self, parent=None):
        PlotSubWidget.__init__(self, parent)
        self.setWindowTitle(tr.tr("Plot properties"))
        self._selected_plot_idx = -1
        self.resize(250, 225)
        self.move(32, 32)
        gboxlayout = self.layout()

        if gboxlayout is None:
            gboxlayout = QtGui.QGridLayout()
            self.setLayout(gboxlayout)

        self._cur_plt_qcb = QtGui.QComboBox()
        self._int_ord_dsp = QtGui.QDoubleSpinBox()
        self._lne_wdt_dsp = QtGui.QDoubleSpinBox()
        self._mrk_sze_dsp = QtGui.QDoubleSpinBox()
        self._mrk_tpe_qcb = QtGui.QComboBox()
        self._lne_tpe_qcb = QtGui.QComboBox()
        self._bar_tpe_qcb = QtGui.QComboBox()
        self._plt_clr_qcb = QtGui.QComboBox()

        for i in plotting.MARKER_TYPES:
            self._mrk_tpe_qcb.addItem(i[1])

        for i in plotting.LINE_TYPES:
            self._lne_tpe_qcb.addItem(i[1])

        for i in plotting.BAR_TYPES:
            self._bar_tpe_qcb.addItem(i[1])

        for i in plotting.COLORS:
            self._plt_clr_qcb.addItem(i[1])

        self.setStyleSheet(
            """
            QLabel#Title
            {
                background-color: lightgray;
                color: black;
                min-height: 15;
            }

            QPushButton#Close
            {
                background-color: lightgray;
                color: black;
                border: none;
                font: bold;
                min-width: 25;
                min-height: 15;
            }

            QPushButton#Close:hover:!pressed
            {
                background-color: black;
                color: white;
            }

            QPushButton#Close:pressed
            {
                background-color: red;
                color: white;
            }
            """)

        self._int_ord_dsp.setSingleStep(0.1)
        self._lne_wdt_dsp.setSingleStep(0.1)
        self._mrk_sze_dsp.setSingleStep(0.5)

        self._int_ord_dsp.setMaximum(1000)

        gboxlayout.addWidget(self._cur_plt_qcb, 1, 0, 1, 2)

        gboxlayout.addWidget(QtGui.QLabel(tr.tr("line color")), 2, 0)
        gboxlayout.addWidget(self._plt_clr_qcb, 2, 1)

        gboxlayout.addWidget(QtGui.QLabel(tr.tr("line type")), 3, 0)
        gboxlayout.addWidget(self._lne_tpe_qcb, 3, 1)

        gboxlayout.addWidget(QtGui.QLabel(tr.tr("marker type")), 4, 0)
        gboxlayout.addWidget(self._mrk_tpe_qcb, 4, 1)

        gboxlayout.addWidget(QtGui.QLabel(tr.tr("errorbars type")), 5, 0)
        gboxlayout.addWidget(self._bar_tpe_qcb, 5, 1)

        gboxlayout.addWidget(QtGui.QLabel(tr.tr("line width")), 6, 0)
        gboxlayout.addWidget(self._lne_wdt_dsp, 6, 1)

        gboxlayout.addWidget(QtGui.QLabel(tr.tr("marker size")), 7, 0)
        gboxlayout.addWidget(self._mrk_sze_dsp, 7, 1)

        gboxlayout.addWidget(QtGui.QLabel(tr.tr("interpolation")), 8, 0)
        gboxlayout.addWidget(self._int_ord_dsp, 8, 1)

        self.setEnabled(True)

        self._cur_plt_qcb.currentIndexChanged.connect(self.currentPlotChanged)
        self._int_ord_dsp.valueChanged.connect(self.setInterpolationOrder)
        self._mrk_sze_dsp.valueChanged.connect(self.setMarkerSize)
        self._lne_wdt_dsp.valueChanged.connect(self.setLineWidth)
        self._mrk_tpe_qcb.currentIndexChanged.connect(self.setMarkerType)
        self._plt_clr_qcb.currentIndexChanged.connect(self.setColor)
        self._lne_tpe_qcb.currentIndexChanged.connect(self.setLineType)
        self._bar_tpe_qcb.currentIndexChanged.connect(self.setBarType)

    def setPlots(self, plots):
        self._cur_plt_qcb.clear()
        for plot in plots:
            self._cur_plt_qcb.addItem(plot.getName())

    def setInterpolationOrder(self, val):
        self.getSelectedPlot().setIterpolationOrder(val)
        self.parent().update()

    def setMarkerSize(self, val):
        self.getSelectedPlot().setMarkerSize(val)
        self.parent().update()

    def setLineWidth(self, val):
        self.getSelectedPlot().setLineWidth(val)
        self.parent().update()

    def setColor(self, idx):
        self.getSelectedPlot().setColorIndex(idx)
        self.parent().update()

    def setMarkerType(self, idx):
        self.getSelectedPlot().setMarkerTypeIndex(idx)
        self.parent().update()

    def setLineType(self, idx):
        self.getSelectedPlot().setLineTypeIndex(idx)
        self.parent().update()

    def setBarType(self, idx):
        self.getSelectedPlot().setBarTypeIndex(idx)
        self.parent().update()

    def updatePlotControls(self):
        plot = self.getSelectedPlot()
        if plot is None:
            return

        int_ord = float(plot.getIterpolationOrder())
        mrk_sze = float(plot.getMarkerSize())
        lne_wdt = float(plot.getLineWidth())

        mrk_tpe_idx = plotting.getMarkerTypeIndex(plot.getMarkerType())
        lne_tpe_idx = plotting.getLineTypeIndex(plot.getLineType())
        bar_tpe_idx = plotting.getBarTypeIndex(plot.getBarType())
        plt_clr_idc = plotting.getColorIndex(plot.getColor())

        self._int_ord_dsp.setValue(int_ord)
        self._mrk_sze_dsp.setValue(mrk_sze)
        self._lne_wdt_dsp.setValue(lne_wdt)
        self._mrk_tpe_qcb.setCurrentIndex(mrk_tpe_idx)
        self._lne_tpe_qcb.setCurrentIndex(lne_tpe_idx)
        self._bar_tpe_qcb.setCurrentIndex(bar_tpe_idx)
        self._plt_clr_qcb.setCurrentIndex(plt_clr_idc)

    def currentPlotChanged(self, plot_idx):
        self._selected_plot_idx = plot_idx
        self.updatePlotControls()

    def getSelectedPlot(self):
        if self._selected_plot_idx < 0:
            self._int_ord_dsp.setEnabled(False)
            self._lne_wdt_dsp.setEnabled(False)
            self._mrk_sze_dsp.setEnabled(False)
            self._mrk_tpe_qcb.setEnabled(False)
            self._lne_tpe_qcb.setEnabled(False)
            self._plt_clr_qcb.setEnabled(False)
            return None
        else:
            self._int_ord_dsp.setEnabled(True)
            self._lne_wdt_dsp.setEnabled(True)
            self._mrk_sze_dsp.setEnabled(True)
            self._mrk_tpe_qcb.setEnabled(True)
            self._lne_tpe_qcb.setEnabled(True)
            self._plt_clr_qcb.setEnabled(True)
            return self.parent().plots[self._selected_plot_idx]


class PlotWidget(QWidget):

    def __init__(self, parent=None):
        QWidget.__init__(self, parent)

        self.plots = []
        self._backend = None
        self.axis_name = ('x', 'y')
        self._inverted_y = False
        self._padding = (60, 160, 60.0, 60.0)
        self._offset = (0, 0)
        self._range_offset = (0, 0)
        self._x_fmt_func = utils.getTimeStr
        self._x_legend = -1
        self._y_legend = -1
        self._show_legend = True
        self._plot_window = (0, 0, 1280, 720)
        self._dialog = PlotPropertyDialogWidget(self)
        self._prop_qpb = Qt.QPushButton(self)

        self._zoom = 1
        self._is_panning = False
        self._movement_start = (0, 0)
        self._movement_end = (0, 0)

        self._prop_qpb.setIcon(utils.getQIcon("gear"))
        self._prop_qpb.setIconSize(QtCore.QSize(16, 16))
        self._prop_qpb.move(2, 2)
        self._prop_qpb.setFlat(True)

        self._dialog.hide()

        self._prop_qpb.clicked.connect(self._dialog.show)

        self.setFocusPolicy(QtCore.Qt.ClickFocus)

    def mousePressEvent(self, event):
        btn = event.button()
        if btn == 1:
            self._is_panning = True
            self._movement_start = (event.x(), event.y())

    def mouseReleaseEvent(self, event):
        btn = event.button()
        if btn == 1:
            self._is_panning = False
            self._movement_end = (event.x(), event.y())
            self.update()

    def mouseMoveEvent(self, event):
        if self._is_panning:
            self._range_offset = (
                event.x() - self._movement_start[0],
                event.y() - self._movement_start[1]
            )
            self.update()

    def zoomIn(self):
        raise NotImplementedError()

    def zoomOut(self):
        raise NotImplementedError()

    def zoomFit(self):
        raise NotImplementedError()

    def showLegend(self):
        self._show_legend = True
        self.update()

    def hideLegend(self):
        self._show_legend = False
        self.update()

    def isLegendVisible(self):
        return self._show_legend

    def setLegendVisible(self, val):
        if val:
            self.showLegend()
        else:
            self.hideLegend()

    def addPlot(self, plt):
        self.plots.append(plt)
        self._dialog.setPlots(self.plots)
        plt.setInvertedY(self._inverted_y)

    def setInvertedY(self, inverted=True):
        self._inverted_y = bool(inverted)
        for plt in self.plots:
            plt.setInvertedY(inverted)
        self.update()

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(painter.Antialiasing)
        return self.render(painter)

    def render(self, painter):

        painter.setWindow(*self._plot_window)
        painter.setBrush(QtCore.Qt.white)
        painter.drawRect(painter.window())

        if not self.plots:
            # no plots to draw
            return

        # computing initial plot ranges
        there_is_a_plot = False
        for plot in self.plots:
            if plot.isHidden():
                continue
            elif not there_is_a_plot:
                there_is_a_plot = True
                vmin, vmax = plot.getYMinMax()
                hmin, hmax = plot.getXMinMax()
                continue
            pvmin, pvmax = plot.getYMinMax()
            phmin, phmax = plot.getXMinMax()
            vmin = min(vmin, pvmin)
            vmax = max(vmax, pvmax)
            hmin = min(hmin, phmin)
            hmax = max(hmax, phmax)

        if not there_is_a_plot:
            vmin = 0
            vmax = 1
            hmin = 0
            hmax = 1

        if hmin == hmax:
            hmax = hmin + 1
        if vmin == vmax:
            hmax = hmin + 1

        # drawing axis
        ranges = plotting.drawAxis(
            painter,
            range_x=(hmin, hmax),
            range_y=(vmin, vmax),
            padding=self._padding,
            offset=self._offset,
            axis_name=self.axis_name,
            inverted_y=self._inverted_y)

        # drawing plots
        painter.setBrush(QtCore.Qt.white)
        y_off = 1.25*painter.fontMetrics().lineSpacing()
        x_off = self._padding[1] - 20
        count = 0
        for plot in self.plots:
            if self._backend is None:
                plot.drawQt(painter,
                            ranges[0],
                            ranges[1],
                            self._padding,
                            self._offset)
                if self._show_legend and plot.isVisible():
                    elx = self._plot_window[2] - x_off
                    ely = self._padding[1] + y_off + y_off*count
                    plot.drawQtLegendElement(painter, elx, ely)
                    count += 1


class PlotViewer(QWidget):

    def __init__(self, parent=None, inverted_y=False):
        QWidget.__init__(self, parent)

        self._pv = PlotWidget(parent=self)

        self._plt_lst_qlw = ToolComboCheckBox(
            tr.tr("lightcurves:"),
            tr.tr("Select the lightcurves to show"))
        self._plt_lst_qlw.itemChanged.connect(self._ccbItemChanged)

        toolbar = Qt.QToolBar('PlotViewerToolBar')

        save_plot_action = QtGui.QAction(
            utils.getQIcon("save-plot"),
            tr.tr('Save the displayed plot to a file'),
            self)

        export_csv_action = QtGui.QAction(
            utils.getQIcon("text-csv"),
            tr.tr('Export plot data to a cvs file'),
            self)

        invert_y_action = QtGui.QAction(
            utils.getQIcon("invert-y-axis"),
            tr.tr('Invert the Y axis'),
            self)
        invert_y_action.setCheckable(True)

        show_legend_action = QtGui.QAction(
            utils.getQIcon("legend"),
            tr.tr('Show plot legend'),
            self)
        show_legend_action.setCheckable(True)

        # TODO: low priority
        #
        # zoom_in_action = QtGui.QAction(
        #     utils.getQIcon("zoom-in"),
        #     tr.tr('Zoom in'),
        #     self)
        #
        # zoom_out_action = QtGui.QAction(
        #     utils.getQIcon("zoom-out"),
        #     tr.tr('Zoom out'),
        #     self)
        #
        # zoom_fit_action = QtGui.QAction(
        #     utils.getQIcon("zoom-fit"),
        #     tr.tr('Zoom fit'),
        #    self)
        #
        # toolbar.addAction(zoom_in_action)
        # toolbar.addAction(zoom_out_action)
        # toolbar.addAction(zoom_fit_action)
        #
        # zoom_in_action.triggered.connect(self._pv.zoomIn)
        # zoom_out_action.triggered.connect(self._pv.zoomOut)
        # zoom_fit_action.triggered.connect(self._pv.zoomFit)

        toolbar.addAction(save_plot_action)
        toolbar.addAction(export_csv_action)
        toolbar.addAction(invert_y_action)
        toolbar.addAction(show_legend_action)
        toolbar.addWidget(self._plt_lst_qlw)

        self._pv.setSizePolicy(
            QtGui.QSizePolicy(QtGui.QSizePolicy.Expanding,
                              QtGui.QSizePolicy.Expanding))

        mainlayout = Qt.QVBoxLayout(self)

        mainlayout.addWidget(toolbar)
        mainlayout.addWidget(self._pv)

        self.setLayout(mainlayout)

        export_csv_action.triggered.connect(self.exportNumericDataCSV)
        save_plot_action.triggered.connect(self.savePlotAsImage)
        show_legend_action.toggled.connect(self._pv.setLegendVisible)
        invert_y_action.toggled.connect(self._pv.setInvertedY)

        show_legend_action.setChecked(True)
        invert_y_action.setChecked(inverted_y)

    def setAxisName(self, xname, yname):
        self._pv.axis_name = (str(xname), str(yname))

    def _ccbItemChanged(self, item):
        plot = self._pv.plots[item.index().row()]
        plot.setVisible(item.checkState())
        self.update()

    def addPlots(self, plots):
        idx = len(self._pv.plots)
        for plot in plots:
            if plot not in self._pv.plots:
                plot.setColor(plotting.getColor(idx))
                self._plt_lst_qlw.addItem(plot.name, checked=plot.isVisible())
                self._pv.addPlot(plot)
                idx += 1

    def savePlotAsImage(self):
        file_name = str(Qt.QFileDialog.getSaveFileName(
            None,
            tr.tr("Save image"),
            os.path.join('lightcurves.jpg'),
            "JPG *.jpg (*.jpg);;"
            "PNG *.png (*.png)",
            None,
            utils.DIALOG_OPTIONS))

        if not file_name.strip():
            return False

        pw = self._pv._plot_window[2]
        ph = self._pv._plot_window[3]

        w = 6400
        h = int(w*ph/pw)

        pltpxm = QtGui.QImage(w, h, QtGui.QImage.Format_ARGB32)
        pltpxm.fill(QtCore.Qt.white)
        painter = QtGui.QPainter(pltpxm)
        painter.setRenderHints(painter.Antialiasing |
                               painter.TextAntialiasing |
                               painter.SmoothPixmapTransform)

        self._pv.render(painter)

        while(painter.isActive()):
            QtGui.QApplication.instance().processEvents()
            painter.end()

        try:
            if not pltpxm.save(file_name):
                utils.showErrorMsgBox(
                    tr.tr("Cannot save the image."),
                    tr.tr("Assure you have the authorization " +
                          "to write the file."))
                return False
        except Exception as exc:
            utils.showErrorMsgBox(
                tr.tr("Cannot create the image file: ")+str(exc),
                tr.tr("Assure you have the authorization " +
                      "to write the file."))
            return False
        else:
            return True

    def exportNumericDataCSV(self):
        file_name = str(Qt.QFileDialog.getSaveFileName(
            None,
            tr.tr("Export data to CSV file"),
            os.path.join('lightcurves.csv'),
            "CSV *.csv (*.csv);;All files (*.*)",
            None,
            utils.DIALOG_OPTIONS))

        if not file_name.strip():
            return False

        csvtable = {}

        for plot in self._pv.plots:
            csvtable[plot.getName()] = [
                plot.getXData(),
                plot.getYData(),
                plot.getXError(),
                plot.getYError(),
            ]

        csvdata = ""
        csvsep = ","
        padding = csvsep*5

        # Header
        header = []
        for plotname in csvtable.keys():
            header.append(plotname)
            csvdata += str(plotname) + padding
        csvdata += '\n'

        for head in header:
            csvdata += "time" + csvsep
            csvdata += "value" + csvsep
            csvdata += "time error" + csvsep
            csvdata += "value error" + csvsep
            csvdata += csvsep
        csvdata += '\n'

        # Curve data
        i = 0
        notcompleted = True
        while notcompleted:
            notcompleted = False
            s = ""
            for head in header:
                plotdata = csvtable[head]
                try:
                    s += str(plotdata[0][i]) + csvsep
                    s += str(plotdata[1][i]) + csvsep
                    s += str(plotdata[2][i]) + csvsep
                    s += str(plotdata[3][i]) + csvsep
                    s += csvsep
                except IndexError:
                    s += padding
                else:
                    notcompleted = True
            csvdata += s+'\n'
            i += 1

        try:
            f = open(file_name, 'w')
        except Exception as exc:
            utils.showErrorMsgBox(
                tr.tr("Cannot create the data file: ")+str(exc),
                tr.tr("Assure you have the authorization to write the file."))
            return False
        else:
            f.write(csvdata)
            return True

    def exportNumericDataODS(self):
        raise NotImplementedError()


class LightCurveViewer(PlotViewer):

    _pltprp_grb_txt = tr.tr("Lightcurve properties")
