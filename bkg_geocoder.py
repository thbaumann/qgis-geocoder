# -*- coding: utf-8 -*-
"""
/***************************************************************************
 BKGGeocoder
                                 A QGIS plugin
 uses BKG geocoding API to geocode adresses
 Generated by Plugin Builder: http://g-sherman.github.io/Qgis-Plugin-Builder/
                              -------------------
        begin                : 2018-10-19
        git sha              : $Format:%H$
        copyright            : (C) 2018 by GGR
        email                : franke@ggr-planung.de
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
"""
from PyQt5.QtCore import (QSettings, QTranslator, qVersion,
                          QCoreApplication, QVariant, Qt, pyqtSignal)
from PyQt5.QtGui import QIcon, QPixmap
from PyQt5.QtWidgets import (QAction, QHBoxLayout, QLabel, QComboBox, QCheckBox,
                             QLineEdit, QInputDialog, QMessageBox)
from qgis.core import (QgsProject, QgsField, QgsVectorLayer, QgsMapLayer,
                       QgsPointXY, QgsGeometry, QgsFeature, QgsWkbTypes,
                       QgsCoordinateReferenceSystem,
                       QgsCoordinateTransform)
import copy
import processing
import os.path
import re

# Initialize Qt resources from file resources.py
from .resources import *

from .bkg_geocoder_dialog import BKGGeocoderDialog
from .dialogs import GeocodeProgressDialog
from .geocode import BKGGeocoder, FieldMap, ResultCache
from .config import Config
from .feature_picker import PickerDock

config = Config()

WKBTYPES = dict([(v, k) for k, v in QgsWkbTypes.__dict__.items()
                 if isinstance(v, int)])

BKG_FIELDS = [
    ('bkg_feature_id', QVariant.Int, 'int4'),
    ('bkg_n_results', QVariant.Int, 'int2'),
    ('bkg_i', QVariant.Double, 'int2'),
    ('bkg_typ', QVariant.String, 'text'),
    ('bkg_text', QVariant.String, 'text'),
    ('bkg_score', QVariant.Double, 'float8')
]


class BKGGeocoderPlugin:
    """QGIS Plugin Implementation."""

    def __init__(self, iface):
        """Constructor.

        :param iface: An interface instance that will be passed to this class
            which provides the hook by which you can manipulate the QGIS
            application at run time.
        :type iface: QgsInterface
        """
        # Save reference to the QGIS interface
        self.iface = iface
        # initialize plugin directory
        self.plugin_dir = os.path.dirname(__file__)
        # initialize locale
        locale = QSettings().value('locale/userLocale')[0:2]
        locale_path = os.path.join(
            self.plugin_dir,
            'i18n',
            'BKGGeocoder_{}.qm'.format(locale))

        if os.path.exists(locale_path):
            self.translator = QTranslator()
            self.translator.load(locale_path)

            if qVersion() > '4.3.3':
                QCoreApplication.installTranslator(self.translator)

        # Create the dialog (after translation) and keep reference
        self.dlg = BKGGeocoderDialog()

        # Declare instance attributes
        self.actions = []
        self.menu = self.tr(u'&BKG Geocoder')
        # TODO: We are going to let the user set this up in a future iteration
        self.toolbar = self.iface.addToolBar(u'BKGGeocoder')
        self.toolbar.setObjectName(u'BKGGeocoder')

        self.canvas = self.iface.mapCanvas()

        self.field_mapping = {}
        self.results_cache = ResultCache()


    # noinspection PyMethodMayBeStatic
    def tr(self, message):
        """Get the translation for a string using Qt translation API.

        We implement this ourselves since we do not inherit QObject.

        :param message: String for translation.
        :type message: str, QString

        :returns: Translated version of message.
        :rtype: QString
        """
        # noinspection PyTypeChecker,PyArgumentList,PyCallByClass
        return QCoreApplication.translate('BKGGeocoder', message)


    def add_action(
        self,
        icon_path,
        text,
        callback,
        enabled_flag=True,
        add_to_menu=True,
        add_to_toolbar=True,
        status_tip=None,
        whats_this=None,
        parent=None):
        """Add a toolbar icon to the toolbar.

        :param icon_path: Path to the icon for this action. Can be a resource
            path (e.g. ':/plugins/foo/bar.png') or a normal file system path.
        :type icon_path: str

        :param text: Text that should be shown in menu items for this action.
        :type text: str

        :param callback: Function to be called when the action is triggered.
        :type callback: function

        :param enabled_flag: A flag indicating if the action should be enabled
            by default. Defaults to True.
        :type enabled_flag: bool

        :param add_to_menu: Flag indicating whether the action should also
            be added to the menu. Defaults to True.
        :type add_to_menu: bool

        :param add_to_toolbar: Flag indicating whether the action should also
            be added to the toolbar. Defaults to True.
        :type add_to_toolbar: bool

        :param status_tip: Optional text to show in a popup when mouse pointer
            hovers over the action.
        :type status_tip: str

        :param parent: Parent widget for the new action. Defaults None.
        :type parent: QWidget

        :param whats_this: Optional text to show in the status bar when the
            mouse pointer hovers over the action.

        :returns: The action that was created. Note that the action is also
            added to self.actions list.
        :rtype: QAction
        """

        icon = QIcon(icon_path)
        action = QAction(icon, text, parent)
        action.triggered.connect(callback)
        action.setEnabled(enabled_flag)

        if status_tip is not None:
            action.setStatusTip(status_tip)

        if whats_this is not None:
            action.setWhatsThis(whats_this)

        if add_to_toolbar:
            self.toolbar.addAction(action)

        if add_to_menu:
            self.iface.addPluginToMenu(
                self.menu,
                action)

        self.actions.append(action)

        return action

    def initGui(self):
        """Create the menu entries and toolbar icons inside the QGIS GUI."""
        # toolbar icon
        icon_path = ':/plugins/bkg_geocoder/icon.png'
        self.add_action(
            icon_path,
            text=self.tr(u'BKG Geocoder'),
            callback=lambda: self.run(),
            parent=self.iface.mainWindow()
        )
        # open dialog on right click feature in legend
        self.legendAction = self.add_action(
            icon_path,
            text=self.tr(u'BKG Geocoder'),
            callback=lambda: self.run(
                layer=self.iface.layerTreeView().currentLayer()
                ),
            parent=self.iface,
            add_to_menu=False,
            add_to_toolbar=False
        )
        self.iface.addCustomActionForLayerType(
            self.legendAction, "", QgsMapLayer.VectorLayer, True)

        # dock for feature picking
        self.picker_dock = PickerDock(self.canvas,
                                      self.results_cache)
        # Geocode button clicked in picker dock
        def on_geocode():
            layer = self.picker_dock.active_layer
            feature = self.picker_dock.active_feature
            self.run(layer=layer, feature=feature)
        self.picker_dock.dlg.geocode_button.clicked.connect(on_geocode)
        #, parent=self.iface.mainWindow())
        self.picker_dock.result_set.connect(
            lambda l, f, r: self.set_result(l, f.id(), r, focus=True))
        self.iface.addDockWidget(Qt.LeftDockWidgetArea, self.picker_dock)

        # available layers are stored in here
        self.layer_list = []
        self.layers = None

        self.dlg.save_settings_button.clicked.connect(self.save_config)
        def refresh():
            idx = self.dlg.layer_combo.currentIndex()
            if (idx == -1):
                return
            layer = self.layer_list[idx]
            self.run(layer=layer)
        self.dlg.refresh_button.clicked.connect(refresh)
        self.dlg.start_button.clicked.connect(self.geocode)

        def index_changed(idx):
            if self.dlg.layer_combo.count() > 0:
                self.fill_mapping(self.layer_list[idx])

        self.dlg.layer_combo.currentIndexChanged.connect(index_changed)

        self.geocoder = BKGGeocoder()

        self.load_config()

    def unload(self):
        """Removes the plugin menu item and icon from QGIS GUI."""
        for action in self.actions:
            self.iface.removePluginMenu(
                self.tr(u'&BKG Geocoder'),
                action)
            self.iface.removeToolBarIcon(action)
        self.iface.removeCustomActionForLayerType(self.legendAction)
        self.iface.removeDockWidget(self.picker_dock)
        self.iface.actionPan().trigger()
        del self.picker_dock
        # remove the toolbar
        del self.toolbar

    def run(self, layer=None, feature=None):
        """Run method that performs all the real work"""
        # show the dialog
        self.dlg.close()
        self.fill_layer_combo(active=layer)
        # disable layer selection if layer is passed
        #self.dlg.layer_combo.setEnabled(layer is None)
        self.dlg.selected_only_check.setEnabled(feature is None)
        # if feature is passed -> select it in QGIS
        # and force geocoding selected only
        if feature:
            self.dlg.selected_only_check.setChecked(True)
            layer.removeSelection()
            layer.select(feature.id())
        self.picker_dock.show()
        self.dlg.show()

    def load_config(self):
        '''
        load the config from config file into the settings-form
        '''
        self.dlg.url_edit.setText(str(config.url))
        self.dlg.api_key_edit.setText(str(config.api_key))

    def save_config(self):
        '''
        save settings-form into config-file
        '''
        config.url = str(self.dlg.url_edit.text())
        config.api_key = str(self.dlg.api_key_edit.text())

        config.write()

    def fill_layer_combo(self, active=None, layers=None):
        '''
        fill the layer combo box
        '''
        if not layers:
            layers = [layer for layer in QgsProject.instance().mapLayers().values()]

        self.layer_list = []
        self.dlg.layer_combo.clear()
        self.dlg.area_combo.clear()
        idx = 0
        i = 0
        for layer in layers:
            if isinstance(layer, QgsVectorLayer):
                self.layer_list.append(layer)
                if layer.wkbType() in [QgsWkbTypes.Polygon,
                                       QgsWkbTypes.MultiPolygon]:
                    self.dlg.area_combo.addItem(layer.name(), layer)
                self.dlg.layer_combo.addItem(layer.name())
                if layer == active:
                    idx = i
                i += 1

        if len(self.layer_list) > 0:
            self.dlg.layer_combo.setCurrentIndex(idx)
            self.fill_mapping(self.layer_list[idx])

    def fill_mapping(self, layer):
        '''
        add field checks depending on given layer to UI and preset
        layer related UI elements
        '''
        fields = layer.fields()
        wkb = layer.wkbType()
        self.dlg.geometry_label.setText(WKBTYPES[wkb])
        # preset option to join results to layer depending on if it is
        # possible or not
        self.dlg.join_source_check.setChecked(wkb == QgsWkbTypes.Point)

        crs = layer.crs().authid() if (wkb != 100) else ''
        self.dlg.crs_label.setText(crs)
        epsg_prefix = 'EPSG:'
        if crs.startswith(epsg_prefix):
            epsg_id = int(crs.replace(epsg_prefix, ''))
        else:
            epsg_id = 4326
        self.dlg.epsg_spin.setValue(epsg_id)

        # remove old widgets
        for i in reversed(range(self.dlg.mapping_layout.count())):
            layout = self.dlg.mapping_layout.itemAt(i).layout()
            for i in reversed(range(layout.count())):
                layout.itemAt(i).widget().deleteLater()
        field_map = self.field_mapping.get(layer.id())
        if not field_map or not field_map.valid(layer):
            field_map = self.field_mapping[layer.id()] = FieldMap(layer)

        bkg_f = [f[0] for f in BKG_FIELDS]
        for field in fields:
            # ignore the added bkg fields
            if field.name() in bkg_f:
                continue
            layout = QHBoxLayout()
            checkbox = QCheckBox()
            checkbox.setText(field.name())
            combo = QComboBox()
            combo.addItem('unspezifisch oder nicht aufgeführte Kombination', None)
            for key, text in self.geocoder.keywords.items():
                combo.addItem(text, key)

            def checkbox_changed(state, combo, field):
                checked = state!=0
                field_map.set_active(field.name(), checked)
                combo.setVisible(checked)
            checkbox.stateChanged.connect(
                lambda s, c=combo, f=field, : checkbox_changed(s, c, f))

            def combo_changed(idx, combo, field):
                field_map.set_keyword(field.name(), combo.itemData(idx))
            combo.currentIndexChanged.connect(
                lambda i, c=combo, f=field : combo_changed(i, c, f))

            layout.addWidget(checkbox)
            layout.addWidget(combo)
            self.dlg.mapping_layout.addLayout(layout)
            checked = field_map.active(field.name())
            keyword = field_map.keyword(field.name())
            checkbox.setChecked(checked)
            if keyword is not None:
                combo_idx = combo.findData(keyword)
                combo.setCurrentIndex(combo_idx)
            combo.setVisible(checked)
        n_selected = layer.selectedFeatureCount()
        self.dlg.n_selected_label.setText(
            '({} Feature(s) selektiert)'.format(n_selected))

    def geocode(self, layer):
        '''
        get parameters for geocoding UI and layer and init the
        geocoding
        '''
        idx = self.dlg.layer_combo.currentIndex()
        if (idx == -1):
            return
        layer = self.layer_list[idx]

        url = config.url.format(key=config.api_key)
        srs = self.dlg.epsg_spin.value()
        target_crs = QgsCoordinateReferenceSystem.fromEpsgId(srs)
        self.geocoder.url = url
        self.geocoder.srs = "EPSG:{}".format(srs)

        field_map = self.field_mapping[layer.id()]

        selected_only = self.dlg.selected_only_check.isChecked()
        join_source = self.dlg.join_source_check.isChecked()
        in_area_only = self.dlg.area_check.isChecked()
        active_count = field_map.count_active()
        area_wkt = None

        if not target_crs.isValid():
            QMessageBox.information(
                self.dlg, 'Fehler',
                (u'Die angegebene EPSG id ist nicht valide.\n\n'
                 u'Start abgebrochen...'))
            return

        if in_area_only:
            combo = self.dlg.area_combo
            area_layer = combo.itemData(combo.currentIndex())
            # ToDo: many selected polygons to multipolygon
            if not area_layer or area_layer.selectedFeatureCount() == 0:
                QMessageBox.information(
                    self.dlg, 'Fehler',
                    (u'Für die Einschränkung der Suchregion muss ein Layer mit '
                     u'einem oder mehreren selektierten '
                     u'Polygonen/Multipolygonen ausgewählt sein\n\n'
                     u'Start abgebrochen...'))
                return
            geometries = get_geometries(
                area_layer, selected=True, target_crs=target_crs)
            g_wkts = [g.asWkt() for g in geometries]
            if len(geometries) > 1:
                # shapely seems to be installed under windows by default but
                # is missing in linux
                try:
                    from shapely.geometry.multipolygon import MultiPolygon
                    from shapely import wkt
                except:
                    QMessageBox.information(
                        self.dlg, 'Fehler',
                        (u'Die Python Bibliothek "shapely" ist '
                         u'nicht installiert. Sie wird für die Zusammenführung '
                         u'der selektierten Polygone (Suchgebiet) benötigt. '
                         u'Installieren Sie sie manuell oder wählen Sie nur ein'
                         u' einzelnes Polygon aus.\n\n'
                         u'Start abgebrochen...'))
                    return
                p = [wkt.loads(w) for w in g_wkts]
                multi = MultiPolygon(p)
                area_wkt = multi.wkt
            else:
                area_wkt = g_wkts[0]

        if active_count == 0:
            QMessageBox.information(
                self.dlg, 'Fehler',
                (u'Es sind keine Adressfelder ausgewählt.\n\n'
                 u'Start abgebrochen...'))
            return

        if selected_only and layer.selectedFeatureCount() == 0:
            QMessageBox.information(
                self.dlg, 'Fehler',
                (u'Die Checkbox "nur selektierte Features" ist aktiviert, '
                 u'obwohl keine Features selektiert sind.\n\n'
                 u'Start abgebrochen...'))
            return

        selected = layer.getSelectedFeatures() if selected_only else None
        # clone layer if requested
        if not join_source:
            name, ok = QInputDialog.getText(
                self.dlg, 'Filter', 'Name des zu erstellenden Layers',
                text=get_unique_layer_name(layer.name()))
            if not ok:
                return
            # clone layer and copy the selections of fields
            orig_map = self.field_mapping[layer.id()]
            layer = clone(layer, name=name, features=selected, srs=srs)
            new_map = FieldMap(layer)
            new_map.mapping = copy.deepcopy(orig_map.mapping)
            self.field_mapping[layer.id()] = new_map
        else:
            if layer.wkbType() != QgsWkbTypes.Point:
                QMessageBox.information(
                    self.dlg, 'Fehler',
                    (u'Der Layer enthält keine Punktgeometrie. Daher können '
                     u'die Ergebnisse nicht direkt dem Layer hinzugefügt '
                     u'werden.\n'
                     u'Fügen Sie dem Layer eine Punktgeometrie hinzu oder '
                     u'deaktivieren Sie die Checkbox '
                     u'"Ausgangslayer aktualisieren".\n\n'
                     u'Start abgebrochen...'))
                return

        if not layer.isEditable():
            layer.startEditing()

        for name, qtype, dbtype, length in BKG_FIELDS:
            if name not in layer.fields().names():
                layer.addAttribute(QgsField(name, qtype, dbtype, len=length))

        def on_progress(feat_id, results):
            self.results_cache.add(layer, feat_id, results)
            fidx = layer.fields().indexFromName
            best, idx = results.best()
            layer.changeAttributeValue(
                feat_id, fidx('bkg_feature_id'), feat_id)
            layer.changeAttributeValue(
                feat_id, fidx('bkg_n_results'), results.count())
            layer.changeAttributeValue(
                feat_id, fidx('bkg_i'),  idx or 0)
            #layer.updateFeature(feature)
            self.set_result(layer, feat_id, best)

        def on_done():
            #layer.commitChanges()
            self.canvas.setExtent(layer.extent())
            self.fill_layer_combo(active=layer)

        # pass selected features to geocoding
        # cloned layers are already reduced to selection
        feature_ids = [f.id() for f in selected] if join_source and selected \
            else None

        self.geocoder.logic_link = 'AND' if self.dlg.and_radio.isChecked() \
            else 'OR'
        self.geocoder.fuzzy = self.dlg.fuzzy_check.isChecked()

        dialog = GeocodeProgressDialog(
            self.geocoder, layer, field_map, on_progress, on_done,
            area_wkt=area_wkt, parent=self.dlg, feature_ids=feature_ids)
        dialog.exec_()
        self.picker_dock.clear()

    def set_result(self, layer, feat_id, result, focus=False):
        '''
        set result to feature of given layer
        focus map canvas on feature if requested
        '''
        if not layer.isEditable():
            layer.startEditing()
        fidx = layer.fields().indexFromName
        if result:
            coords = result.coordinates
            geom = QgsGeometry.fromPointXY(QgsPointXY(coords[0], coords[1]))
            layer.changeGeometry(feat_id, geom)
            layer.changeAttributeValue(
                feat_id, fidx('bkg_typ'), result.typ)
            layer.changeAttributeValue(
                feat_id, fidx('bkg_text'), result.text)
            layer.changeAttributeValue(
                feat_id, fidx('bkg_score'), result.score)
        else:
            layer.changeAttributeValue(
                feat_id, fidx('bkg_typ'), '')
            layer.changeAttributeValue(
                feat_id, fidx('bkg_score'), 0)
        #layer.updateFeature(feature)
        if focus:
            layer.removeSelection()
            layer.select(feat_id)
            self.canvas.zoomToSelected(layer)

def clone(layer, srs='4326', name=None, features=None):
    '''
    clone given layer, adds Point geometry with given srs
    optional names it
    data of new layer is based on all features of origin layer or given features
    '''
    features = features or layer.getFeatures()
    name = name or layer.name() + '__clone'

    clone = QgsVectorLayer('Point?crs=epsg:{}'.format(srs),
                           name,
                           'memory')

    data = clone.dataProvider()
    attr = layer.dataProvider().fields().toList()
    data.addAttributes(attr)
    clone.updateFields()
    data.addFeatures([f for f in features])
    QgsProject.instance().addMapLayer(clone)
    return clone

def get_geometries(layer, selected=False, target_crs=None):
    '''
    get geometries of layer (optional selected only)
    transform them to given target crs (optional)
    '''
    features = layer.selectedFeatures() if selected else layer.getFeatures()
    geometries = [f.geometry() for f in features]
    if target_crs:
        source_crs = layer.crs()
        trans = QgsCoordinateTransform(source_crs, target_crs,
                                       QgsProject.instance())
        for geom in geometries:
            geom.transform(trans)
    return geometries

def get_unique_layer_name(name):
    '''
    look for given layername in project,
    if it already exists a suffix is prepended to make it unique
    '''
    orig_name = name
    retry = True
    i = 2
    while retry:
        retry = False
        for layer in QgsProject.instance().mapLayers().values():
            if layer and layer.name() == name:
                name = orig_name + '_{}'.format(i)
                retry = True
                i += 1
                break
    return name
