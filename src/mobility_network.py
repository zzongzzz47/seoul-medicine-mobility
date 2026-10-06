"""Reusable walking graph with edge-based connectors and explicit exclusions."""
from collections import Counter, defaultdict
from pathlib import Path
import json
import xml.etree.ElementTree as ET
import networkx as nx
import numpy as np
from pyproj import Transformer
from shapely import LineString, Point, Polygon, STRtree

ROOT = Path(__file__).resolve().parents[1]
TO_XY = Transformer.from_crs(4326, 5179, always_xy=True)
TO_LL = Transformer.from_crs(5179, 4326, always_xy=True)

def xy(record):
    return np.array(TO_XY.transform(record['lon'], record['lat']))

def permitted(tags):
    foot = tags.get('foot', '')
    if foot in ('no', 'private', 'use_sidepath'): return False
    if tags.get('access') in ('no', 'private') and foot not in ('yes', 'designated', 'permissive'): return False
    if tags.get('highway') in ('motorway','motorway_link','trunk','trunk_link','construction','proposed','raceway','busway','platform') and foot not in ('yes','designated'): return False
    return tags.get('area') != 'yes'

class WalkingNetwork:
    def __init__(self, area):
        folder = ROOT / 'data/raw/expanded_osm'
        manifest = json.loads((folder/'manifest.json').read_text())
        self.bbox = manifest['areas'][area]['bbox']
        nodes, ways = {}, {}
        for item in manifest['files']:
            if item['area'] != area: continue
            root = ET.parse(ROOT/item['file']).getroot()
            for n in root.findall('node'):
                key = int(n.attrib['id'])
                if key not in nodes or int(n.attrib.get('version','0')) > nodes[key]['version']:
                    nodes[key] = dict(lon=float(n.attrib['lon']), lat=float(n.attrib['lat']),
                                      version=int(n.attrib.get('version','0')),
                                      tags={t.attrib['k']:t.attrib['v'] for t in n.findall('tag')})
            for way in root.findall('way'):
                key = int(way.attrib['id'])
                if key not in ways or int(way.attrib.get('version','0')) > ways[key]['version']:
                    ways[key] = dict(nodes=[int(n.attrib['ref']) for n in way.findall('nd')],
                                     version=int(way.attrib.get('version','0')),
                                     tags={t.attrib['k']:t.attrib['v'] for t in way.findall('tag')})
        self.positions = {n:xy(r) for n,r in nodes.items()}
        self.graph = nx.DiGraph()
        self.segments = []
        kinds, omitted = Counter(), Counter()
        for wid, way in ways.items():
            tags = way['tags']; kind = tags.get('highway')
            if not kind: continue
            if not permitted(tags): omitted[kind] += 1; continue
            kinds[kind] += 1
            for a,b in zip(way['nodes'][:-1], way['nodes'][1:]):
                if a not in nodes or b not in nodes or a == b: continue
                if any(not permitted(nodes[n]['tags']) for n in (a,b)): continue
                length = float(np.linalg.norm(self.positions[a]-self.positions[b]))
                if length < .001: continue
                direction = tags.get('oneway:foot','no')
                forward, backward = direction != '-1', direction not in ('yes','1','true')
                attr = dict(length=length, steps=kind=='steps', highway=kind, way_id=wid)
                # Coordinate-identical ways do not create crossings unless OSM nodes are shared.
                if forward: self.graph.add_edge(a,b,**attr)
                if backward: self.graph.add_edge(b,a,**attr)
        # One geometry per pair, preserving explicit pedestrian direction restrictions.
        seen = set()
        for a,b,d in list(self.graph.edges(data=True)):
            key = frozenset((a,b))
            if key in seen: continue
            seen.add(key)
            line = LineString([self.positions[a],self.positions[b]])
            self.segments.append((a,b,line,dict(d), self.graph.has_edge(a,b), self.graph.has_edge(b,a)))
        self.lines = [s[2] for s in self.segments]
        self.tree = STRtree(self.lines)
        self.snaps = {}
        w,s,e,n = self.bbox
        # Densified projected extraction boundary for distance-to-edge screening.
        outline = [(w+(e-w)*t,s) for t in np.linspace(0,1,101)] + [(e,s+(n-s)*t) for t in np.linspace(0,1,101)] + [(e-(e-w)*t,n) for t in np.linspace(0,1,101)] + [(w,n-(n-s)*t) for t in np.linspace(0,1,101)]
        self.boundary = Polygon([TO_XY.transform(*p) for p in outline])
        self.audit = dict(area=area,nodes=len(nodes),ways=len(ways),walk_segments=len(self.segments),
                          way_kinds=dict(kinds),omitted_way_kinds=dict(omitted),bbox=self.bbox,
                          explicit_foot_oneway=sum(w['tags'].get('oneway:foot') in ('yes','1','true','-1') for w in ways.values()))

    def attach(self, records, max_offset=80):
        """Call once with all demand points, candidates, bins, and stops."""
        if self.snaps: raise RuntimeError('Attach all records together once, so original segments are split consistently.')
        pending = defaultdict(list)
        for r in records:
            rid = r['id']
            if rid in self.snaps: raise ValueError(f'Duplicate point ID: {rid}')
            p = Point(xy(r)); idx = int(self.tree.nearest(p)); line=self.lines[idx]
            offset = float(line.distance(p)); projection=float(line.project(p))
            self.snaps[rid] = dict(offset_m=offset,matched=offset<=max_offset,segment=idx,
                                   boundary_margin_m=float(p.distance(self.boundary.boundary)))
            if offset > max_offset: continue
            snap = 'SNAP_'+rid; q=line.interpolate(projection)
            self.positions[snap] = np.array([q.x,q.y]); self.positions[rid] = xy(r)
            self.graph.add_edge(rid,snap,length=offset,steps=False,highway='connector',way_id=None)
            self.graph.add_edge(snap,rid,length=offset,steps=False,highway='connector',way_id=None)
            pending[idx].append((projection,snap))
        for idx,entries in pending.items():
            a,b,line,attr,forward,backward = self.segments[idx]
            if self.graph.has_edge(a,b): self.graph.remove_edge(a,b)
            if self.graph.has_edge(b,a): self.graph.remove_edge(b,a)
            chain=sorted([(0.,a),(line.length,b)]+entries,key=lambda p:p[0])
            for (s,n),(t,m) in zip(chain[:-1],chain[1:]):
                edge={**attr,'length':max(0.,t-s)}
                if forward: self.graph.add_edge(n,m,**edge)
                if backward: self.graph.add_edge(m,n,**edge)
        self.audit.update(connected_points=sum(r['matched'] for r in self.snaps.values()),
                          unconnected_points=sum(not r['matched'] for r in self.snaps.values()),
                          graph_nodes=self.graph.number_of_nodes(),graph_arcs=self.graph.number_of_edges())

    def graph_for(self, no_tagged_steps=False):
        if not no_tagged_steps: return self.graph
        return nx.subgraph_view(self.graph, filter_edge=lambda a,b:not self.graph[a][b]['steps'])

    def distances(self, source, targets, reverse=False, no_tagged_steps=False):
        graph=self.graph_for(no_tagged_steps)
        if reverse: graph=graph.reverse(copy=False)
        d = nx.single_source_dijkstra_path_length(graph,source,weight='length') if source in graph else {}
        return np.array([d.get(t,np.inf) for t in targets])

    def nearest(self, sources, targets, reverse=False, no_tagged_steps=False):
        graph=self.graph_for(no_tagged_steps)
        if reverse: graph=graph.reverse(copy=False)
        sources=[s for s in sources if s in graph]
        if not sources: return np.full(len(targets),np.inf), [None]*len(targets)
        d,paths=nx.multi_source_dijkstra(graph,sources,weight='length')
        return np.array([d.get(t,np.inf) for t in targets]),[paths[t][0] if t in paths else None for t in targets]
