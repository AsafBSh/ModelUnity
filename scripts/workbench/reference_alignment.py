"""CPU orthographic silhouette comparison with explicit user calibration."""
import numpy as np
from PIL import Image, ImageDraw
from scipy.ndimage import distance_transform_edt, binary_erosion


def compare_reference(mesh, reference, yaw=0, pitch=0, scale=0.8, offset_x=0, offset_y=0, size=512):
    if reference is None:
        raise ValueError('Upload an isolated reference with an alpha mask.')
    if size not in (256, 512, 1024):
        raise ValueError('Choose 256, 512 or 1024 comparison pixels.')
    values = np.asarray([yaw,pitch,scale,offset_x,offset_y], dtype=float)
    if not np.isfinite(values).all() or not 0.01 <= scale <= 4 or abs(offset_x)>2 or abs(offset_y)>2:
        raise ValueError('Invalid alignment parameters.')
    rgba = reference.convert('RGBA')
    if rgba.getchannel('A').getextrema()[0] == 255:
        raise ValueError('Reference has no foreground mask. Remove its background or correct its alpha first.')
    # Letterbox without stretching the reference.
    rgba.thumbnail((size,size),Image.Resampling.LANCZOS)
    canvas=Image.new('RGBA',(size,size));canvas.paste(rgba,((size-rgba.width)//2,(size-rgba.height)//2))
    ref=np.asarray(canvas.getchannel('A'))>127
    if not ref.any():raise ValueError('Reference foreground is empty.')
    xyz=np.asarray(mesh.vertices,dtype=float)
    extent=np.ptp(xyz,axis=0).max()
    if not np.isfinite(xyz).all() or extent<=0:raise ValueError('Mesh has invalid bounds.')
    xyz=(xyz-(xyz.min(0)+xyz.max(0))/2)/extent
    a,b=np.deg2rad([yaw,pitch]);ca,sa,cb,sb=np.cos(a),np.sin(a),np.cos(b),np.sin(b)
    rotation=np.array([[ca,0,sa],[sb*sa,cb,-sb*ca],[-cb*sa,sb,cb*ca]])
    xy=(xyz@rotation.T)[:,:2]*[size*scale,-size*scale]+[size*(.5+offset_x),size*(.5+offset_y)]
    silhouette=Image.new('L',(size,size));draw=ImageDraw.Draw(silhouette)
    if len(mesh.faces)>500000:raise ValueError('Use a working mesh with at most 500,000 faces for comparison.')
    for face in mesh.faces:draw.polygon([tuple(p) for p in xy[face]],fill=255)
    actual=np.asarray(silhouette)>0
    if not actual.any():raise ValueError('Model is outside the comparison frame.')
    edge_a=actual & ~binary_erosion(actual);edge_r=ref & ~binary_erosion(ref)
    distances=np.r_[distance_transform_edt(~edge_r)[edge_a],distance_transform_edt(~edge_a)[edge_r]]
    union=actual|ref
    pixels=np.asarray(canvas.convert('RGB')).copy()//3
    pixels[ref & ~actual]=[242,112,103];pixels[actual & ~ref]=[54,205,211];pixels[actual & ref]=[84,182,124]
    report={'projection':'user-aligned orthographic silhouette, no camera calibration',
            'intersection_over_union':float((actual&ref).sum()/union.sum()),
            'mean_boundary_error_pixels':float(distances.mean()),'p95_boundary_error_pixels':float(np.percentile(distances,95)),
            'pixels':size,'yaw':yaw,'pitch':pitch,'scale':scale,'offset':[offset_x,offset_y],
            'limitation':'Geometry silhouette only: ignores texture transparency. Measures this masked view/alignment, not camera calibration, depth, hidden details or real dimensions.'}
    return Image.fromarray(pixels),report
