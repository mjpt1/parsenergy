from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from apps.ml.services import predict_next, recommend_maintenance


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def prediction_api(request):
    values = [float(v) for v in request.query_params.get('values', '').split(',') if v]
    result = predict_next(values)
    recommendation = recommend_maintenance(result)
    return Response({
        'prediction': result.__dict__,
        'maintenance': recommendation.__dict__,
    })
