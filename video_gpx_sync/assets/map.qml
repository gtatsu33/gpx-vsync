import QtQuick
import QtLocation
import QtPositioning

Map {
    id: root
    width: 800
    height: 600

    plugin: Plugin {
        id: osmPlugin
        name: "osm"

        // Qt標準のosmプラグインは、デフォルトのactiveMapTypeがQt側の
        // プロキシ経由Thunderforestタイル（APIキー要求）になっている。
        // osm.mapping.host単体では効かず、osm.mapping.custom.hostで
        // 独自のCustomMapタイプを追加した上で、下のonSupportedMapTypesChanged
        // で明示的にactiveMapTypeへ切り替える必要がある（Qt 6.11で確認）。
        // implement.txt記載の仕様（tile.openstreetmap.org直接・
        // attribution "OpenStreetMap contributors"のみ）に合わせる。
        PluginParameter {
            name: "osm.useragent"
            value: "GPX-VSync/1.0"
        }
        PluginParameter {
            name: "osm.mapping.custom.host"
            value: "https://tile.openstreetmap.org/"
        }
        PluginParameter {
            name: "osm.mapping.custom.copyright"
            value: "&copy; OpenStreetMap contributors"
        }
    }

    center: QtPositioning.coordinate(35.0, 135.0)
    zoomLevel: 13

    // ---- 地図操作（パン・ズーム）----
    // QtLocationのMap型はLeafletと異なり、デフォルトではマウス/
    // トラックパッド操作でのパン・ズームに対応していない（Qt公式
    // ドキュメントで確認済み）。PinchHandler/WheelHandler/DragHandlerを
    // 明示的に追加する必要がある（doc.qt.io/qt-6/qml-qtlocation-map.html
    // のInteractivityサンプルに準拠）。
    property geoCoordinate startCentroid

    PinchHandler {
        id: pinchHandler
        target: null
        onActiveChanged: if (active) {
            root.startCentroid = root.toCoordinate(pinchHandler.centroid.position, false)
        }
        onScaleChanged: (delta) => {
            root.zoomLevel += Math.log2(delta)
            root.alignCoordinateToPoint(root.startCentroid, pinchHandler.centroid.position)
        }
        onRotationChanged: (delta) => {
            root.bearing -= delta
            root.alignCoordinateToPoint(root.startCentroid, pinchHandler.centroid.position)
        }
        grabPermissions: PointerHandler.TakeOverForbidden
    }

    WheelHandler {
        id: wheelHandler
        acceptedDevices: Qt.platform.pluginName === "cocoa" || Qt.platform.pluginName === "wayland"
            ? PointerDevice.Mouse | PointerDevice.TouchPad
            : PointerDevice.Mouse
        rotationScale: 1 / 120
        property: "zoomLevel"
    }

    DragHandler {
        id: dragHandler
        target: null
        onTranslationChanged: (delta) => root.pan(-delta.x, -delta.y)
    }

    // ---- ルート線（現行map_template.htmlのloadRoute/updateRouteRanges相当） ----
    property var routeLatLngs: []
    property var routeSegments: []

    function loadRoute(latlngs) {
        routeLatLngs = latlngs;
        var flags = [];
        for (var i = 0; i < latlngs.length; i++) flags.push(true);
        updateRouteRanges(flags);

        if (latlngs.length > 0) {
            var coords = [];
            for (var i = 0; i < latlngs.length; i++) {
                coords.push(QtPositioning.coordinate(latlngs[i][0], latlngs[i][1]));
            }
            root.visibleRegion = QtPositioning.rectangle(coords);
        }
    }

    function updateRouteRanges(inRangeFlags) {
        // Leaflet版のsplitIntoSegments/renderRouteSegments相当。
        // 区間の継ぎ目で線が途切れないよう、前の点も含めて分割する。
        var segments = [];
        var current = null;
        for (var i = 0; i < routeLatLngs.length; i++) {
            var flag = inRangeFlags[i];
            if (!current || current.inRange !== flag) {
                if (current) segments.push(current);
                current = { inRange: flag, path: [] };
                if (i > 0) {
                    current.path.push(
                        QtPositioning.coordinate(routeLatLngs[i - 1][0], routeLatLngs[i - 1][1])
                    );
                }
            }
            current.path.push(QtPositioning.coordinate(routeLatLngs[i][0], routeLatLngs[i][1]));
        }
        if (current) segments.push(current);
        routeSegments = segments;
    }

    // ---- 現在地マーカー（現行map_template.htmlのupdateMarker/hideMarker相当） ----
    property var markerCoordinate: QtPositioning.coordinate(0, 0)
    property bool markerVisible: false

    function updateMarker(lat, lon) {
        markerCoordinate = QtPositioning.coordinate(lat, lon);
        markerVisible = true;
        // Leaflet版のmap.panTo相当。現在地マーカーが常に視野内に
        // 収まるよう自動スクロールする（spec.txt 5-2節）。
        root.center = markerCoordinate;
    }

    function hideMarker() {
        markerVisible = false;
    }

    function clearMap() {
        routeLatLngs = [];
        routeSegments = [];
        markerVisible = false;
    }

    MapItemView {
        model: root.routeSegments
        delegate: MapPolyline {
            line.width: 3
            line.color: modelData.inRange ? "#16a34a" : "#6b7280"
            path: modelData.path
        }
    }

    MapQuickItem {
        coordinate: root.markerCoordinate
        visible: root.markerVisible
        anchorPoint.x: markerShape.width / 2
        anchorPoint.y: markerShape.height / 2

        sourceItem: Rectangle {
            id: markerShape
            width: 16
            height: 16
            radius: 8
            color: "#f03"
            opacity: 0.8
            border.color: "red"
            border.width: 1
        }
    }

    onSupportedMapTypesChanged: {
        for (var i = 0; i < supportedMapTypes.length; i++) {
            if (supportedMapTypes[i].name === "Custom URL Map") {
                activeMapType = supportedMapTypes[i];
                return;
            }
        }
        // 見つからない場合は最後のタイプ（custom.host指定時は
        // 通常末尾に追加される）にフォールバック
        if (supportedMapTypes.length > 0) {
            activeMapType = supportedMapTypes[supportedMapTypes.length - 1];
        }
    }

    // QtLocationのMap型はLeafletと異なりattributionを自動描画しない。
    // OSMタイル利用ポリシー・implement.txt記載の要件により表示必須。
    Rectangle {
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        width: attributionText.implicitWidth + 8
        height: attributionText.implicitHeight + 4
        color: "#ccffffff"

        Text {
            id: attributionText
            anchors.centerIn: parent
            text: "© OpenStreetMap contributors"
            font.pixelSize: 11
            color: "#333333"
        }
    }
}
