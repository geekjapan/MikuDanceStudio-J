"""Add side-effect-free observers to an isolated source copy; never change production sources."""
from pathlib import Path
import hashlib
import json
import shutil
import difflib

def prepare(source, destination):
    shutil.copytree(source, destination, dirs_exist_ok=True)
    changes = {}
    def edit(name, replacements):
        path=destination/name
        original=path.read_text()
        text=original
        for old,new,count in replacements:
            assert text.count(old)==count,(name,old,text.count(old))
            text=text.replace(old,new)
        path.write_text(text)
        changes[name]={'original':hashlib.sha256(original.encode()).hexdigest(),'observed':hashlib.sha256(text.encode()).hexdigest()}
        (destination.parent/(Path(name).name+'.diff')).write_text(''.join(difflib.unified_diff(original.splitlines(True),text.splitlines(True),fromfile=name,tofile=name)))
    edit('BulletCollision/CollisionDispatch/btUnionFind.h',[
        ('struct\tbtElement','class btUnionFind;\nvoid island_observe_uf(const char*,int,int,const btUnionFind&);\nstruct\tbtElement',1),
        ('if (i == j) \n\t\t\t\treturn;', 'if (i == j) { island_observe_uf("unite",p,q,*this); return; }',1),
        ('#endif //USE_PATH_COMPRESSION', '#endif //USE_PATH_COMPRESSION\n            island_observe_uf("unite",p,q,*this);',1),
        ('int find(int x)\n\t\t{', 'int find(int x)\n\t\t{ int observed_input=x;',1),
        ('return x; ', 'island_observe_uf("find",observed_input,x,*this);\n            return x; ',1),
    ])
    edit('BulletCollision/CollisionDispatch/btUnionFind.cpp',[
        ('m_elements[i].m_id = i; m_elements[i].m_sz = 1; \n\t} ', 'm_elements[i].m_id = i; m_elements[i].m_sz = 1; \n\t} \n    island_observe_uf("reset",N,0,*this);',1),
        ('m_elements.quickSort(btUnionFindElementSortPredicate());','m_elements.quickSort(btUnionFindElementSortPredicate());\n    island_observe_uf("sort",0,0,*this);',1),
    ])
    edit('BulletCollision/CollisionDispatch/btSimulationIslandManager.cpp',[
        ('//#include <stdio.h>', 'void island_observe_objects(const char*,int,int,int,btCollisionWorld*);\n//#include <stdio.h>',1),
        ('\n\t}\n\n\t\n\tint i;\n\tint maxNumManifolds', '\n        island_observe_objects("sleep",islandId,allSleeping,endIslandIndex-startIslandIndex,collisionWorld);\n\t}\n\n\t\n\tint i;\n\tint maxNumManifolds',1),
        ('\n\t}\n}\n\n\n\n///@todo:', '\n        island_observe_objects("wake",i,0,0,collisionWorld);\n\t}\n}\n\n\n\n///@todo:',1),
        ('\n\t\t\tif (!islandSleeping)\n', '\n            island_observe_objects("scan",islandId,islandSleeping,startManifoldIndex,collisionWorld);\n\t\t\tif (!islandSleeping)\n',1),
        ('startManifoldIndex = endManifoldIndex;', 'startManifoldIndex = endManifoldIndex;\n                island_observe_objects("cursor",islandId,startManifoldIndex,numIslandManifolds,collisionWorld);',1),
    ])
    edit('BulletDynamics/Dynamics/btDiscreteDynamicsWorld.cpp',[
        ('sortedConstraints.quickSort(btSortConstraintOnIslandPredicate());','sortedConstraints.quickSort(btSortConstraintOnIslandPredicate());\n    island_observe_constraints(sortedConstraints);',1),
        ('#include "btDiscreteDynamicsWorld.h"','#include "btDiscreteDynamicsWorld.h"\nvoid island_observe_constraints(const btAlignedObjectArray<btTypedConstraint*>&);',1),
    ])
    (destination.parent/'observer-sources.json').write_text(json.dumps(changes,indent=2)+'\n')
